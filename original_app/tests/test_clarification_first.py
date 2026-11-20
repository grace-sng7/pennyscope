"""All provider calls are mocked: no financial prompt leaves this test process."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
from legacy_main import app
import orchestration as o
import extraction_service as e
import extraction_evidence as evidence

QUESTION="My friends want to do a spring break trip to Miami but I don't know if I can afford it; I think it may cost 3000 to go, but I'm earning 200 a month"


def factor(name,value,unit,quote,source='stated'):
    return dict(variable=name,value=value,unit=unit,role='known',source=source,source_detail='User supplied value',relevant=True,evidence=dict(source='question',quote=quote))


def extraction(bad=False):
    facts=[factor('goal_amount',3000,'$','I think it may cost 3000 to go','inferred'),factor('monthly_income',200,'$/month',"I'm earning 200 a month"),factor('goal_deadline','spring break','text','spring break')]
    if bad:facts.append(factor('monthly_contribution',200,'$/month',QUESTION))
    return dict(target_variable='affordability_status',factors=facts,goal_summary='Check whether the trip fits.',confidence_note='Cost is a user estimate; other personal facts remain unknown.')


def request(ex):return dict(original_question=QUESTION,assumptions=ex['assumptions'],extraction_meta=ex)
def context():return dict(user_message=QUESTION,reference_date='2026-11-18',timezone='America/New_York')


class ClarificationFirst(unittest.TestCase):
    def setUp(self):o.CACHE.clear();e.PENDING_ROUTES.clear()

    def test_earnings_are_not_a_savings_contribution(self):
        for text in ("I'm earning 200 a month",'I have $350 saved and earn $200 a month','I earn $200 and save $50 monthly',"I can't save $200 a month"):
            self.assertFalse(evidence._contribution_supported(200,text),text)
        for text in ('I can save $200 a month','I can put $200 each month toward the trip','I have $200 left after all expenses'):
            self.assertTrue(evidence._contribution_supported(200,text),text)

    def test_initial_understood_shows_required_unknowns_and_no_main_call(self):
        with TestClient(app) as client,patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},extraction()]) as selection,patch.object(o,'call_json') as main:
            r=client.post('/extract',json=context());self.assertEqual(r.status_code,200);ex=r.json()
            result=client.post('/calculate',json=request(ex)).json()
        self.assertEqual(selection.call_count,2);main.assert_not_called()
        given={a['variable']:a['value'] for a in ex['assumptions'] if a['value'] is not None}
        self.assertEqual(given['monthly_income'],200);self.assertNotIn('monthly_contribution',given)
        unknown={q['target_variable'] for q in ex['clarification_questions']}
        self.assertEqual(unknown,{'current_savings','contribution_months','monthly_expenses'})
        self.assertTrue(all(q['required'] for q in ex['clarification_questions']))
        self.assertIn('after your expenses',ex['assistant_message'])
        self.assertEqual(result['status'],'needs_input');self.assertEqual(len(result['missing_inputs']),1);self.assertIsNone(result['answer'])

    def test_rejected_earnings_as_contribution_cannot_escape_through_plain_fallback(self):
        with TestClient(app) as client,patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},extraction(True),extraction(True)]),patch('gemini_gateway.call_text') as plain,patch.object(o,'call_json') as main:
            r=client.post('/extract',json=context())
        self.assertEqual(r.status_code,200);ex=r.json();plain.assert_not_called();main.assert_not_called()
        self.assertNotIn('chat_fallback',ex);self.assertTrue(ex['clarification_questions'])
        self.assertFalse(any(a['variable']=='monthly_contribution' and a['value'] is not None for a in ex['assumptions']))
        self.assertEqual(next(a['value'] for a in ex['assumptions'] if a['variable']=='monthly_income'),200)

    def test_progressive_answers_block_main_until_all_required_facts_are_supplied(self):
        with TestClient(app) as client:
            with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},extraction()]):ex=client.post('/extract',json=context()).json()
            for value,remaining in [('0',2),('4',1),('100',0)]:
                empty=dict(target_variable='affordability_status',factors=[],goal_summary='Updated supplied information.',confidence_note='No estimates.')
                with patch('gemini_gateway.call_json',return_value=empty),patch.object(o,'call_json') as main:
                    ex=client.post('/correct',json={**context(),'previous_extraction':ex,'user_correction':value}).json()
                    self.assertEqual(len(ex['clarification_questions']),remaining)
                    if remaining:
                        result=client.post('/calculate',json=request(ex)).json();self.assertEqual(result['status'],'needs_input');self.assertIsNone(result['answer'])
                    main.assert_not_called()
            draft=dict(model='savings_goal',target_variable='affordability_status',inputs=dict(solve_for='affordability',current_savings=0,monthly_income=200,monthly_spending=100,target=3000,months=4),
                bindings=dict(current_savings='current_savings',monthly_income='monthly_income',monthly_spending='monthly_expenses',target='goal_amount',months='contribution_months'),
                results={'affordability_status':'No'},factors=[dict(variable='affordability_status',value='No',unit='text',role='derived',source='inferred',source_detail='Main calculation')],headline='The trip does not fit these numbers.',calculation='(200-100)*4=400; 400<3000',assumptions=[])
            with patch.object(o,'call_json',side_effect=[draft,{'decision':'approved'}]) as main:
                result=client.post('/calculate',json=request(ex)).json()
            self.assertEqual(main.call_count,2);self.assertEqual(result['verification']['status'],'matched');self.assertIn('No',result['answer']['headline'])
            self.assertEqual(next(a['value'] for a in ex['assumptions'] if a['variable']=='current_savings'),0)

    def test_explicit_contribution_satisfies_capacity_without_asking_for_expenses(self):
        raw=extraction();raw['factors'] += [factor('current_savings',0,'$','0 saved'),factor('contribution_months',4,'months','four monthly deposits'),factor('monthly_contribution',100,'$/month','save $100 monthly')]
        q=QUESTION+'; I have 0 saved and will make four monthly deposits. I can save $100 monthly.'
        with TestClient(app) as client,patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},raw]):
            ex=client.post('/extract',json={**context(),'user_message':q}).json()
        self.assertEqual(ex['clarification_questions'],[])
        self.assertFalse(any(f['variable']=='monthly_expenses' and f.get('relevant',True) for f in ex['factors']))

    def test_calculation_failure_with_missing_inputs_still_asks_instead_of_guessing(self):
        with TestClient(app) as client,patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},extraction()]):ex=client.post('/extract',json=context()).json()
        with TestClient(app) as client,patch.object(o,'calculate',side_effect=ValueError('Forced failure')),patch('gemini_gateway.call_text') as plain:
            r=client.post('/calculate',json=request(ex))
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['status'],'needs_input');plain.assert_not_called()
