"""Grace presentation attaches to real model selection/verification without new requirements."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import orchestration as o
from legacy_main import app


def scenario(model,target,values,inputs,bindings,result,unit='$',question='User financial question'):
    req=dict(original_question=question,assumptions=[dict(variable=k,value=v,unit=u,source='stated',source_detail='User supplied fact') for k,v,u in values],extraction_meta=dict(model=model,target_variable=target,selection_state={'reference_date':'2026-11-17'}))
    draft=dict(model=model,target_variable=target,inputs=inputs,bindings=bindings,results={target:result},factors=[dict(variable=target,value=result,unit=unit,role='derived',source='inferred',source_detail='Main primary calculation')],headline='Main answer',calculation='Main arithmetic',assumptions=[])
    return req,draft


def savings_case():
    return scenario('savings_goal','affordability_status',[('monthly_income',2000,'$/month'),('monthly_expenses',1650,'$/month'),('current_savings',1200,'$'),('goal_amount',3000,'$'),('goal_deadline',8,'months')],
        dict(solve_for='affordability',monthly_income=2000,monthly_spending=1650,current_savings=1200,target=3000,months=8),
        dict(monthly_income='monthly_income',monthly_spending='monthly_expenses',current_savings='current_savings',target='goal_amount',months='goal_deadline'),'Yes','text',
        'I earn $2000 after tax monthly, spend $1650 monthly and have $1200 available for a $3000 goal in eight months. Can I afford it?')


def budget_case():
    return scenario('budget_cash_flow','projected_surplus',[('monthly_surplus',700,'$/month'),('recurring_cost',1400,'$/month'),('replaced_recurring_cost',1000,'$/month')],
        dict(monthly_surplus=700,spending_change=1400,replaced_recurring_cost=1000),dict(monthly_surplus='monthly_surplus',spending_change='recurring_cost',replaced_recurring_cost='replaced_recurring_cost'),300,'$/month',
        'I have $700 left each month after all expenses including $1000 rent. If I move to $1400 monthly rent, what will I have left?')


def calculate_case(case):
    req,draft=case;o.CACHE.clear()
    with TestClient(app) as client,patch.object(o,'call_json',side_effect=[draft,{'decision':'approved'}]) as llm:
        r=client.post('/calculate',json=req)
    assert r.status_code==200,r.text
    return r.json(),llm.call_count


class AnswerPresentation(unittest.TestCase):
    def test_full_savings_keeps_grace_funding_budget_timeline_options_and_narrative(self):
        result,calls=calculate_case(savings_case());v=result['visuals']
        self.assertEqual(calls,2);self.assertEqual(result['verification']['status'],'matched')
        self.assertEqual(v['funding'],dict(goal=3000,from_income=2800,from_savings=200,short=0))
        self.assertEqual(v['budget']['income'],2000);self.assertEqual(v['budget']['left_over'],0)
        self.assertEqual(v['timeline'][-1],dict(month=8,set_aside=2800));self.assertEqual(v['base_date'],'2026-11-17')
        self.assertGreaterEqual(len(v['options']),2);self.assertGreaterEqual(len(result['narrative']['suggestions']),2)
        self.assertIn('$350',result['narrative']['text']);self.assertEqual(result['missing_inputs'],[])

    def test_budget_surplus_is_not_mislabeled_income_and_never_needs_deadline(self):
        result,_=calculate_case(budget_case());v=result['visuals']
        self.assertEqual(result['verification']['main_value'],300)
        self.assertEqual(v['budget_now']['basis'],'surplus');self.assertEqual(v['budget_now']['income'],700)
        self.assertEqual(v['budget_after']['goal'],400);self.assertEqual(v['budget_after']['left_over'],300)
        self.assertEqual(result['missing_inputs'],[]);self.assertNotIn('months',v)
        self.assertIn('$300',result['narrative']['text']);self.assertGreaterEqual(len(v['options']),2)

    def test_reverse_savings_200_needs_no_income_for_chart(self):
        case=scenario('savings_goal','required_monthly_savings',[('current_savings',200,'$'),('goal_amount',1200,'$'),('goal_deadline',5,'months')],
            dict(solve_for='monthly_required',current_savings=200,target=1200,months=5),dict(current_savings='current_savings',target='goal_amount',months='goal_deadline'),200,'$/month')
        r,_=calculate_case(case);self.assertEqual(r['verification']['main_value'],200)
        self.assertEqual(r['missing_inputs'],[]);self.assertNotIn('budget',r['visuals']);self.assertEqual(r['visuals']['funding']['from_income'],1000)

    def test_mismatch_omits_conflicting_visuals_but_keeps_main_narrative_and_warning(self):
        req,draft=budget_case();draft['results']['projected_surplus']=900;draft['factors'][0]['value']=900
        draft['narrative']=dict(text='You would have $300 left.',suggestions=[],primary_value=300)
        r,_=calculate_case((req,draft));self.assertEqual(r['verification']['status'],'mismatch')
        self.assertIn('$900',r['answer']['headline']);self.assertIsNone(r['visuals'])
        self.assertIn('$900',r['narrative']['text']);self.assertNotIn('$300',r['narrative']['text'])

    def test_optional_failure_never_hides_the_answer_or_changes_call_count(self):
        with patch('answer_presentation.attach',side_effect=ValueError('Forced optional presentation failure')):
            r,calls=calculate_case(savings_case())
        self.assertEqual(r['status'],'conditional');self.assertIsNotNone(r['answer']);self.assertEqual(calls,2)

    def test_main_narrative_is_used_only_when_target_and_amounts_are_grounded(self):
        req,draft=savings_case()
        draft['narrative']=dict(text='Your $350 monthly margin gives this plan room. Compare the options before deciding.',suggestions=['What if I save $300 each month?'],primary_value='Yes')
        r,_=calculate_case((req,draft));self.assertIn('$350',r['narrative']['text']);self.assertNotEqual(r['narrative']['text'],draft['narrative']['text'])
        draft['narrative']['text']='For this plan, save $225 monthly.'
        r,_=calculate_case((req,draft));self.assertNotIn('$225',r['narrative']['text'])
        draft['narrative']['text']='You can spend $99999 now.'
        r,_=calculate_case((req,draft));self.assertNotIn('99999',r['narrative']['text'])

    def test_bill_split_has_narrative_without_savings_or_budget_chart_requirements(self):
        case=scenario('bill_split','amounts_owed',[('participants',3,None),('total_bill',90,'$'),('split_method','equal',None)],dict(people=3,total=90,method='equal'),dict(people='participants',total='total_bill',method='split_method'),30)
        r,_=calculate_case(case);self.assertEqual(r['missing_inputs'],[]);self.assertIsNone(r['visuals']);self.assertEqual(r['verification']['status'],'matched')
        self.assertTrue(r['narrative']['suggestions'])

    def test_shortfall_options_do_not_claim_an_unaffordable_monthly_deposit_fits(self):
        req,draft=savings_case()
        for fact in req['assumptions']:
            if fact['variable']=='goal_deadline':fact['value']=4
        draft['inputs']['months']=4;draft['results']['affordability_status']='No';draft['factors'][0]['value']='No'
        result,_=calculate_case((req,draft));self.assertEqual(result['verification']['status'],'matched')
        self.assertEqual(result['visuals']['funding']['short'],400)
        options=result['visuals']['options']
        self.assertTrue(any('Delay' in o['label'] and o['feasible'] for o in options))
        self.assertTrue(any('Lower the goal' in o['label'] and o['goal']<3000 for o in options))
        self.assertFalse(next(o for o in options if o['label']=='Keep existing savings untouched')['feasible'])

    def test_malformed_narrative_keeps_available_visuals_and_template(self):
        req,draft=savings_case();draft['narrative']={'primary_value':'Yes','text':123,'suggestions':'bad'}
        r,_=calculate_case((req,draft));self.assertIsNotNone(r['visuals']);self.assertIsInstance(r['narrative']['text'],str)

    def test_summary_is_short_and_timing_working_stays_in_disclosure(self):
        import json
        record=json.loads((Path(__file__).parent/'regression_artifacts/backend_live_audit.json').read_text())
        ex=record['after']['runs'][0]['extraction'];given={a['variable']:a for a in ex['assumptions']}
        import answer_presentation as presentation
        response=record['after']['runs'][0]['calculation']
        inputs=dict(current_savings=900,monthly_income=2400,target=2500,months=4,spending_entries=[dict(name='rent',amount=1000),dict(name='everything else',amount=600)])
        result=presentation.attach(response,{},dict(input_plan=dict(inputs=inputs)),{},given,dict(monthly_savings=800,months=4))
        text=result['narrative']['text']
        self.assertLessEqual(len(text.split()),45)
        self.assertIn('$800',text);self.assertIn('March 2027',text)
        self.assertNotIn('2026-11-18',text);self.assertNotIn('partial month',text)
        self.assertNotIn('Compare the options',text)
        self.assertTrue(any(e.get('id')=='calendar-timing' and '2026-11-18' in e['text'] for e in result['assumptions']))
        self.assertEqual(result['answer'],response['answer']);self.assertEqual(result['verification'],response['verification'])
        self.assertTrue(result['visuals']);self.assertEqual(len(result['narrative']['suggestions']),2)
