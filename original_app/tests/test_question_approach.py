"""Scoped Main approaches never become registered models or Python programs."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
from main import app
from factor_registry import REGISTRIES
import orchestration as o

QUESTION='I have $220 in checking, a $300 bill due on the 4th, and a $150 paycheck on the 6th. How much extra cash do I need before the bill is due?'
EARLY=QUESTION.replace('6th','3rd')


def draft(question,early=False):
    facts=[('checking',220,'$','$220 in checking'),('bill_amount',300,'$','$300 bill'),('bill_day',4,'day','on the 4th'),('paycheck',150,'$','$150 paycheck'),('paycheck_day',3 if early else 6,'day','on the 3rd' if early else 'on the 6th')]
    factors=[dict(variable=name,value=value,unit=unit,role='known',source='stated',source_detail=quote) for name,value,unit,quote in facts]
    factors += [dict(variable='cash_at_due_date',value=370 if early else 220,unit='$',role='derived',source='inferred',source_detail='Checking plus income arriving before the bill date.'),dict(variable='cash_needed',value=0 if early else 80,unit='$',role='derived',source='inferred',source_detail='Maximum of zero and bill minus cash_at_due_date.')]
    return dict(calculation='220 + 150 = 370; max(0, 300 - 370) = 0' if early else 'Paycheck arrives later. max(0, 300 - 220) = 80',approach='Order events by date and compute the positive shortfall at payment time.',target_variable='cash_needed',factors=factors,headline=f'You need ${0 if early else 80} before the bill is due.',missing_inputs=[])


class QuestionApproach(unittest.TestCase):
    def test_both_cash_timing_cases_use_main_with_examples_and_no_registration(self):
        before=dict(REGISTRIES)
        with TestClient(app) as client:
            for q,early in [(QUESTION,False),(EARLY,True)]:
                with patch('gemini_gateway.call_json',side_effect=[{'model':'gap'},draft(q,early)]) as main,patch.object(o,'_verify') as verifier,patch.object(o,'calculate') as existing:
                    ex=client.post('/extract',json=dict(user_message=q,reference_date='2026-11-16',timezone='America/New_York')).json()
                    result=client.post('/calculate',json=dict(original_question=q,assumptions=ex['assumptions'],extraction_meta=ex)).json()
                self.assertEqual(result['answer']['headline'],f'You need ${0 if early else 80} before the bill is due.')
                self.assertEqual(result['missing_inputs'],[]);self.assertEqual(result['verification']['status'],'unverified')
                self.assertIsNone(result['model']);self.assertEqual(result['target_variable'],'cash_needed')
                self.assertEqual({f['role'] for f in result['factors']},{'known','derived'})
                self.assertEqual(main.call_count,2);self.assertEqual(main.call_args.kwargs['stage'],'main_calculation')
                for model in before:self.assertIn(model,main.call_args.args[1])
                verifier.assert_not_called();existing.assert_not_called()
        self.assertEqual(dict(REGISTRIES),before)

    def test_missing_required_input_returns_one_question_without_warning(self):
        q=QUESTION.replace('$300','an unspecified amount for the')
        raw=draft(QUESTION)
        raw['factors']=[f for f in raw['factors'] if f['variable'] not in ('bill_amount','cash_at_due_date','cash_needed')]
        raw['factors'] += [dict(variable=k,value=None,unit='$',role='missing',source='missing',source_detail='Not supplied' if k=='bill_amount' else 'Requested output') for k in ('bill_amount','cash_needed')]
        raw['missing_inputs']=[dict(variable='bill_amount',label='How much is the bill?')];raw['headline']=''
        with TestClient(app) as client,patch('gemini_gateway.call_json',return_value=raw):
            r=client.post('/calculate',json=dict(original_question=q,assumptions=[],extraction_meta={'routing':{'model':'gap'}}))
        self.assertEqual(r.status_code,200);result=r.json()
        self.assertEqual(len(result['missing_inputs']),1);self.assertEqual(result['message'],'How much is the bill?')
        self.assertIsNone(result['verification']);self.assertIsNone(result['answer'])

    def test_card_metadata_failure_keeps_main_answer_without_another_llm(self):
        raw=draft(QUESTION);raw['factors'][0]['value']=999
        with TestClient(app) as client,patch('gemini_gateway.call_json',return_value=raw),patch('gemini_gateway.call_text') as plain:
            r=client.post('/calculate',json=dict(original_question=QUESTION,assumptions=[],extraction_meta={'routing':{'model':'gap'}}))
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['chat_fallback']['text'],'You need $80 before the bill is due.')
        self.assertEqual(r.json()['chat_fallback']['verification']['status'],'unverified');plain.assert_not_called()
        kept={f['variable']:f['value'] for f in r.json()['factors']}
        self.assertNotIn('checking',kept);self.assertEqual(kept['bill_amount'],300)

    def test_existing_model_success_path_is_unchanged(self):
        covered={'status':'conditional','answer':{'headline':'Each person owes $30.'}}
        with TestClient(app) as client,patch.object(o,'calculate',return_value=covered) as existing,patch('question_approach.calculate') as proposed:
            r=client.post('/calculate',json=dict(original_question='Split $120 equally four ways.',assumptions=[],extraction_meta={'model':'bill_split','routing':{'model':'bill_split'}}))
        self.assertEqual(r.json()['answer']['headline'],'Each person owes $30.');existing.assert_called_once();proposed.assert_not_called()

    def test_registered_model_coverage_gap_uses_scoped_approach(self):
        with TestClient(app) as client,patch.object(o,'calculate',return_value={'status':'unsupported','message':'Unsupported timing'}),patch('gemini_gateway.call_json',return_value=draft(QUESTION)):
            r=client.post('/calculate',json=dict(original_question=QUESTION,assumptions=[],extraction_meta={'model':'budget_cash_flow'}))
        self.assertEqual(r.status_code,200);self.assertEqual(r.json()['answer']['headline'],'You need $80 before the bill is due.')
