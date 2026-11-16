"""Handoff regressions use real routing/extraction validation and calculators.
Only provider outputs are mocked; no paid provider is needed for disagreement.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from fastapi import HTTPException
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import orchestration as o
import extraction_service as e
import calculation_handoff as h
from factor_registry import REGISTRIES
from main import app
from test_selection_stages import selected
from test_dynamic_models import scenario

APPROVED={'decision':'approved','headline':'Reviewed result','detail':'Based on your stated facts.','assumptions':[]}


def wire(question, extraction):
    return dict(original_question=question, assumptions=extraction['assumptions'],extra_inputs={},answers=[],parameters={},
                extraction_meta={k:v for k,v in extraction.items() if k not in ('assumptions','clarification_questions')})


def extract(question,model,target,values):
    response=selected(target,values)
    for f in response['factors']:
        if f['variable'] in ('monthly_surplus','recurring_cost','monthly_contribution'):f['unit']='$/month'
    with patch('gemini_gateway.call_json',side_effect=[{'model':model},response]):
        return e.extract(question,'2026-11-16','America/New_York')


class Handoff(unittest.TestCase):
    def setUp(self):
        o.CACHE.clear();o.PENDING_REVIEWS.clear();e.PENDING_ROUTES.clear()

    def test_recurring_rent_with_stated_surplus(self):
        q='I have $700 monthly surplus after expenses. Can an additional $500 monthly rent increase fit?'
        ex=extract(q,'budget_cash_flow','projected_surplus',{'monthly_surplus':700,'recurring_cost':500})
        draft,_=scenario('budget_cash_flow',dict(monthly_surplus=700,spending_change=500),'projected_surplus','$/month',
                         {'monthly_surplus':'monthly_surplus','spending_change':'recurring_cost'})
        draft['results']={'scenario_monthly_surplus':200}
        req=wire(q,ex)
        with patch.object(o,'call_json',side_effect=[draft,APPROVED]) as llm:
            result=o.calculate(req)
        self.assertEqual(result['status'],'conditional')
        self.assertIn('$200.00',result['answer']['headline'])
        payload=json.loads(llm.call_args_list[0].args[1])
        self.assertEqual(payload['resolved_selection']['model'],'budget_cash_flow')
        self.assertEqual(llm.call_count,2)
        self.assertNotIn('monthly_income',draft['inputs'])
        # Main remains primary; verifier independently resolves the target.
        self.assertEqual(o._verify(draft)['scenario_monthly_surplus'],'200.00')

    def test_reverse_savings_no_existing_contribution_or_income_needed(self):
        q='I have $200 saved and want $1200 in five months. How much must I save monthly?'
        ex=extract(q,'savings_goal','required_monthly_savings',dict(current_savings=200,goal_amount=1200,goal_deadline=5))
        draft,_=scenario('savings_goal',dict(solve_for='monthly_required',current_savings=200,target=1200,months=5),
                         'required_monthly_savings','$/month',{'current_savings':'current_savings','target':'goal_amount','months':'goal_deadline'})
        draft['results']={'required_monthly_savings':200}
        with patch.object(o,'call_json',side_effect=[draft,APPROVED]):result=o.calculate(wire(q,ex))
        self.assertIn('$200.00',result['answer']['headline'])

    def test_budget_to_bill_correction_reroutes_and_clears_old_facts(self):
        q='I have $700 monthly surplus. Can an additional $500 monthly rent fit?'
        old=extract(q,'budget_cash_flow','projected_surplus',dict(monthly_surplus=700,recurring_cost=500))
        correction='New question: split a $120 dinner equally among four people.'
        with patch('gemini_gateway.call_json',side_effect=[{'model':'bill_split','transition':'new'},selected('amounts_owed',dict(total_bill=120,participants=4,split_method='equal'))]):
            ex=e.correct(q,'2026-11-16','America/New_York',old,correction)
        self.assertNotIn('monthly_surplus',{a['variable'] for a in ex['assumptions']})
        draft,_=scenario('bill_split',dict(method='equal',people=4,total=120),'amounts_owed','text',
                         {'method':'split_method','people':'participants','total':'total_bill'})
        draft['results']={'amounts_owed':dict.fromkeys(['Person 1','Person 2','Person 3','Person 4'],'30.00')}
        with patch.object(o,'call_json',side_effect=[draft,APPROVED]):result=o.calculate(wire(correction,ex))
        owed=json.loads(next(f['value'] for f in result['factors'] if f['variable']=='amounts_owed'))
        self.assertEqual(list(owed.values()),['30.00']*4)

    def test_unresolved_disagreement_has_exactly_one_reevaluation(self):
        q='I have $700 monthly surplus. Can $500 monthly rent fit?'
        ex=extract(q,'budget_cash_flow','projected_surplus',dict(monthly_surplus=700,recurring_cost=500))
        mismatch={'model':'savings_goal','target_variable':'affordability_status','intent_mismatch':True,'mismatch_reason':'Unsure whether ongoing or one time.'}
        with patch.object(o,'call_json',side_effect=[mismatch,mismatch]) as main,patch('gemini_gateway.call_json',side_effect=[
            {'model':'budget_cash_flow'},selected('projected_surplus',dict(monthly_surplus=700,recurring_cost=500))]) as selection,patch.object(o,'_verify') as verify:
            result=o.calculate(wire(q,ex))
        self.assertEqual(result['status'],'needs_input');self.assertEqual(len(result['missing_inputs']),1)
        self.assertEqual(main.call_count,2);self.assertEqual(selection.call_count,2);verify.assert_not_called()
        self.assertFalse(o.CACHE);self.assertFalse(o.PENDING_REVIEWS)

    def test_reevaluation_model_change_preserves_correction_and_drops_budget(self):
        q='I have $700 monthly surplus and a $120 bill equally shared by four people. How much does each owe?'
        ex=extract(q,'budget_cash_flow','projected_surplus',dict(monthly_surplus=700,recurring_cost=120))
        req=wire(q,ex)
        req['extra_inputs']['total_bill']=160 # latest explicit user correction
        bill,_=scenario('bill_split',dict(method='equal',people=4,total=160),'amounts_owed','text',
                        {'method':'split_method','people':'participants','total':'total_bill'})
        bill['results']={'amounts_owed':dict.fromkeys(['Person 1','Person 2','Person 3','Person 4'],'40.00')}
        mismatch={'model':'bill_split','target_variable':'amounts_owed','intent_mismatch':True,'mismatch_reason':'User asks allocation.'}
        with patch.object(o,'call_json',side_effect=[mismatch,bill,APPROVED]) as main,patch('gemini_gateway.call_json',side_effect=[
            {'model':'bill_split'},selected('amounts_owed',dict(total_bill=120,participants=4,split_method='equal'))]) as selection:
            result=o.calculate(req)
        self.assertEqual(result['model'],'bill_split')
        context=json.loads(selection.call_args_list[1].args[1])
        self.assertEqual(context['previous_factors'],[])
        second=json.loads(main.call_args_list[1].args[1])
        self.assertNotIn('monthly_surplus',{a['variable'] for a in second['request']['assumptions']})
        self.assertEqual(next(f['value'] for f in second['request']['extraction_meta']['factors'] if f['variable']=='total_bill'),160)
        self.assertEqual(json.loads(next(f['value'] for f in result['factors'] if f['variable']=='amounts_owed')),dict.fromkeys(['Person 1','Person 2','Person 3','Person 4'],'40.00'))
        # Cached rerouted results retain their resolved evidence, not the old budget facts.
        with patch.object(o,'call_json') as llm:cached=o.calculate(req)
        llm.assert_not_called();self.assertEqual(cached['factors'],result['factors'])

    def test_missing_target_and_missing_required_fact_stop_before_main(self):
        for target,values,variable in [(None,{},'target_selection'),('required_monthly_savings',{'goal_amount':1200,'goal_deadline':5},'current_savings')]:
            req=wire('Savings',dict(model='savings_goal',target_variable=target,assumptions=[dict(variable=k,value=v,unit=None,source='stated',source_detail='User') for k,v in values.items()]))
            with patch.object(o,'call_json') as main:result=o.calculate(req)
            main.assert_not_called();self.assertEqual(len(result['missing_inputs']),1)
            self.assertEqual(result['missing_inputs'][0]['variable'],variable)

    def test_gap_and_multiple_never_call_main(self):
        for route,status in [('gap','unsupported'),('multiple','needs_input'),('ambiguous','needs_input')]:
            req=wire('Question',dict(assumptions=[],routing={'model':route}))
            with patch.object(o,'call_json') as main:result=o.calculate(req)
            main.assert_not_called();self.assertEqual(result['status'],status)

    def test_same_model_target_change_reextracts(self):
        q='I have $200 saved, want $1200 in five months, and contribute $100 monthly. What monthly amount is needed?'
        ex=extract(q,'savings_goal','projected_savings',dict(current_savings=200,goal_amount=1200,goal_deadline=5,monthly_contribution=100))
        draft,_=scenario('savings_goal',dict(solve_for='monthly_required',current_savings=200,target=1200,months=5),'required_monthly_savings','$/month',
            {'current_savings':'current_savings','target':'goal_amount','months':'goal_deadline'})
        mismatch={'model':'savings_goal','target_variable':'required_monthly_savings'}
        with patch.object(o,'call_json',side_effect=[mismatch,draft,APPROVED]),patch('gemini_gateway.call_json',side_effect=[
            {'model':'savings_goal'},selected('required_monthly_savings',{})]) as selection:
            result=o.calculate(wire(q,ex))
        self.assertEqual(result['target_variable'],'required_monthly_savings')
        self.assertEqual(selection.call_count,2)

    def test_all_registry_targets_have_input_rules(self):
        for registry in REGISTRIES.values():
            for target in registry.targets:
                groups=registry.required_inputs(target,{})
                self.assertTrue(groups)
                for group in groups:
                    self.assertTrue(all(target not in option for option in group))
                    self.assertTrue(all(set(option)<=set(registry.factors) for option in group))

    def test_target_clarification_answer_resumes_extraction(self):
        q='I have $200 saved and want $1200 in five months.'
        req=wire(q,dict(model='savings_goal',target_variable=None,assumptions=[],selection_state={'model':'savings_goal','active_question':q}))
        req['extra_inputs']={'target_selection':'How much should I save monthly?'}
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal','transition':'continuation'},selected('required_monthly_savings',dict(current_savings=200,goal_amount=1200,goal_deadline=5))]):
            updated=h.apply_intent_answer(req)
        selection,missing=h.resolve(updated,o._facts(updated))
        self.assertIsNone(missing);self.assertEqual(selection['target_variable'],'required_monthly_savings')

    def test_http_missing_input_is_one_question(self):
        req=wire('How much to save monthly?',dict(model='savings_goal',target_variable='required_monthly_savings',assumptions=[]))
        with TestClient(app) as client,patch.object(o,'call_json') as llm:r=client.post('/calculate',json=req)
        self.assertEqual(r.status_code,200);self.assertEqual(len(r.json()['missing_inputs']),1);llm.assert_not_called()

    def test_rerouted_inspector_failure_keeps_main_visible_and_cached(self):
        q='I have $700 monthly surplus and a $120 dinner equally shared by four people.'
        ex=extract(q,'budget_cash_flow','projected_surplus',dict(monthly_surplus=700,recurring_cost=120))
        req=wire(q,ex)
        draft,_=scenario('bill_split',dict(method='equal',people=4,total=120),'amounts_owed','text',
                         {'method':'split_method','people':'participants','total':'total_bill'})
        mismatch={'model':'bill_split','target_variable':'amounts_owed','intent_mismatch':True}
        with patch.object(o,'call_json',side_effect=[mismatch,draft,HTTPException(502,'Provider unavailable'),APPROVED]) as llm,patch('gemini_gateway.call_json',side_effect=[
            {'model':'bill_split'},selected('amounts_owed',dict(total_bill=120,participants=4,split_method='equal'))]) as selection,patch.object(o,'_verify',wraps=o._verify) as verifier:
            first=o.calculate(req)
            result=o.calculate(req)
            self.assertEqual(first,result)
        self.assertEqual(result['model'],'bill_split');self.assertEqual(selection.call_count,2)
        self.assertEqual(verifier.call_count,1)
        self.assertEqual([c.kwargs['stage'] for c in llm.call_args_list],['main_calculation','main_calculation','inspector'])
        self.assertFalse(o.PENDING_REVIEWS)

    def test_required_alternatives_cover_savings_and_debt(self):
        cases=[('savings_goal','months_to_goal',dict(available_savings=200,goal_amount=1200,monthly_surplus=100)),
               ('savings_goal','projected_savings',dict(current_savings=0,goal_deadline=5,monthly_income=1000,monthly_expenses=900)),
               ('debt_repayment','monthly_interest',dict(principal_balance=1000,apr=0)),
               ('debt_repayment','required_monthly_payment',dict(principal_balance=1000,apr=0,payoff_months=10)),
               ('bill_split','settlements',dict(amounts_owed='{"A":60,"B":60}',amounts_paid='{"A":120,"B":0}'))]
        for model,target,values in cases:
            req=wire('Question',dict(model=model,target_variable=target,assumptions=[dict(variable=k,value=v,unit=None,source='stated',source_detail='User') for k,v in values.items()]))
            selection,missing=h.resolve(req,o._facts(req))
            self.assertIsNone(missing,(model,target));self.assertEqual(selection['target_variable'],target)

    def test_units_and_solver_cannot_drift(self):
        selection={'model':'savings_goal','target_variable':'required_monthly_savings'}
        with self.assertRaises(ValueError):h.validate_mode({'model':'savings_goal','target_variable':'required_monthly_savings','inputs':{'solve_for':'future_balance'}},selection)
        draft,_=scenario('budget_cash_flow',dict(monthly_surplus=700,spending_change=500),'projected_surplus','$/month')
        facts={k:dict(value=v,unit='$/week') for k,v in draft['inputs'].items()}
        with self.assertRaises(ValueError):o._validate(draft,facts,{})


if __name__=='__main__':unittest.main()
