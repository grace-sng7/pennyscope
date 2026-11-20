"""Stage-order and isolation tests: fixtures are LLM responses, never keyword routing."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import extraction_service as e
import factor_selection as fs
from factor_registry import REGISTRIES,get_registry
from legacy_main import app


def selected(target,values):
    factors=[]
    for name,value in values.items():
        if isinstance(value,(dict,list)):value=json.dumps(value)
        unit='months' if name in ('goal_deadline','payoff_months') else '%' if name=='apr' else 'text' if isinstance(value,str) else '$'
        factors.append(dict(variable=name,value=value,unit=unit,role='known',source='stated',source_detail='User supplied this value',relevant=True))
    factors.append(dict(variable=target,value=None,unit=None,role='missing',source='missing',source_detail='Target to solve later',relevant=True))
    return {'target_variable':target,'factors':factors,'goal_summary':'Selected goal','confidence_note':'Test interpretation'}

SAMPLES=[
 ('budget_cash_flow','I earn $900 every two weeks, spend $1650/month; can a $90 monthly gym fit?','projected_surplus',{'income_entries':[{'amount':900,'frequency':'biweekly'}],'monthly_spending':1650,'recurring_cost':90}),
 ('savings_goal','I have $200 saved and want $1200 in five months. How much must I save monthly?','required_monthly_savings',{'current_savings':200,'goal_amount':1200,'goal_deadline':5}),
 ('bill_split','Split $120 equally among four people.','amounts_owed',{'total_bill':120,'participants':4,'split_method':'equal'}),
 ('debt_repayment','When will my $5000 loan at 8% with $200 monthly be paid?','estimated_payoff_months',{'principal_balance':5000,'apr':8,'monthly_payment':200}),
]


class SelectionStages(unittest.TestCase):
    def setUp(self):e.PENDING_ROUTES.clear()
    def test_four_real_registry_branches_and_two_narrow_calls(self):
        for model,question,target,values in SAMPLES:
            with patch('gemini_gateway.call_json',side_effect=[{'model':model},selected(target,values)]) as llm,patch('orchestration.calculate') as downstream:
                result=e.extract(question,'2026-11-10','America/New_York')
            self.assertEqual([c.kwargs['stage'] for c in llm.call_args_list],['model_routing','factor_extraction'])
            self.assertEqual(result['model'],model);self.assertEqual(result['target_variable'],target)
            self.assertTrue(set(f['variable'] for f in result['factors'])<=set(get_registry(model).factors))
            context=json.loads(llm.call_args_list[1].args[1])
            self.assertEqual(context['selected_model_registry']['model'],model)
            self.assertEqual(set(context['selected_model_registry']['factors']),set(get_registry(model).factors))
            downstream.assert_not_called()
            self.assertNotIn('missing_inputs',result)
            self.assertEqual(result['clarification_questions'],[])

    def test_registry_lookup_occurs_between_calls(self):
        events=[]
        def lookup(model):events.append('python_registry');return get_registry(model)
        def llm(*args,**kw):
            events.append(kw['stage'])
            return {'model':'savings_goal'} if kw['stage']=='model_routing' else selected('months_to_goal',{'monthly_contribution':200})
        with patch.object(e,'get_registry',side_effect=lookup),patch('gemini_gateway.call_json',side_effect=llm):e.extract('I contribute $200 monthly toward $3000. How long?','2026-11-10','UTC')
        self.assertEqual(events,['model_routing','python_registry','factor_extraction'])

    def test_all_declared_targets_are_accepted_with_code_selected_input_questions(self):
        for model,registry in REGISTRIES.items():
            for target in registry.targets:
                with patch('gemini_gateway.call_json',side_effect=[{'model':model},selected(target,{})]) as llm:
                    result=e.extract('Interpret this target','2026-11-10','UTC')
                self.assertEqual(result['target_variable'],target)
                self.assertEqual(llm.call_count,2)
                self.assertTrue(all(q['target_variable']!=result['target_variable'] and q.get('required') for q in result['clarification_questions']))

    def test_gap_ambiguous_multiple_stop_before_factor_selection(self):
        cases=[{'model':'gap'},{'model':'ambiguous','clarification':'Do you mean a purchase or shared allocation?'},{'model':'multiple','models':['budget_cash_flow','debt_repayment']}]
        for route in cases:
            with patch('gemini_gateway.call_json',return_value=route) as llm,patch.object(e,'get_registry') as registry:
                result=e.extract('Question','2026-11-10','UTC')
            self.assertEqual(llm.call_count,1);registry.assert_not_called()
            self.assertIsNone(result['model']);self.assertEqual(result['routing']['model'],route['model'])

    def test_invalid_router_cannot_instruct_next_stage(self):
        for route in [{'model':'unknown'},{'model':'budget_cash_flow','next_stage':'calculate'},{'model':'multiple','models':['bill_split','bill_split']}]:
            with patch('gemini_gateway.call_json',return_value=route) as llm,self.assertRaises(HTTPException):e.extract('Question','2026-11-10','UTC')
            self.assertEqual(llm.call_count,1)

    def test_factor_call_cannot_switch_models_or_invent_factors(self):
        for key,value in [('model','debt_repayment'),('next_stage','calculate'),('factors',selected('apr',{})['factors'])]:
            output=selected('projected_surplus',{});output[key]=value
            with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},output]),self.assertRaises(HTTPException):e.extract('Budget','2026-11-10','UTC')

    def test_disallowed_target_and_derived_math_rejected(self):
        for output in [selected('required_monthly_payment',{}),{**selected('projected_surplus',{}),'factors':[dict(variable='projected_surplus',value=210,unit='$/month',role='derived',source='inferred',source_detail='LLM arithmetic')]}]:
            with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},output]),self.assertRaises(HTTPException):e.extract('Budget','2026-11-10','UTC')

    def test_correction_stays_in_branch_and_preserves_unmentioned_known_values(self):
        output=selected('required_monthly_savings',{'current_savings':200,'goal_amount':1200,'goal_deadline':5})
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},output]):previous=e.extract('I have $200 saved and want $1200 in five months','2026-11-10','UTC')
        before=copy.deepcopy(previous)
        with patch('gemini_gateway.call_json',return_value=selected('required_monthly_savings',{'goal_amount':1500})) as llm:
            result=e.correct('Savings','2026-11-10','UTC',previous,'Actually the goal is $1500')
        self.assertEqual(llm.call_count,1);self.assertEqual(llm.call_args.kwargs['stage'],'factor_extraction')
        values={a['variable']:a['value'] for a in result['assumptions']}
        self.assertEqual(values['goal_amount'],1500);self.assertEqual(values['current_savings'],200);self.assertEqual(values['goal_deadline'],5)
        self.assertEqual(previous,before);self.assertEqual(result['selection_state']['revision'],1)

    def test_effective_local_answers_override_old_factor_metadata(self):
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},selected('months_to_goal',{})]):previous=e.extract('Goal','2026-11-10','UTC')
        previous['assumptions'].append(dict(variable='current_savings',value=400,unit='$',source='stated',source_detail='Local answer'))
        with patch('gemini_gateway.call_json',return_value=selected('months_to_goal',{})):
            result=e.correct('Goal','2026-11-10','UTC',previous,'current_savings: 400')
        self.assertEqual(next(a['value'] for a in result['assumptions'] if a['variable']=='current_savings'),400)

    def test_history_profile_and_raw_frequency_reach_only_selected_schema(self):
        with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},selected('monthly_surplus',{'income_entries':[{'amount':900,'frequency':'biweekly'}]})]) as llm:
            result=e.extract('I earn $900 every two weeks','2026-11-10','UTC',history=[{'role':'user','content':'My rent is $1000'}],financial_profile={'monthly_spending':1650,'apr':8})
        context=json.loads(llm.call_args.args[1]);self.assertEqual(context['financial_profile'],{'monthly_spending':1650})
        self.assertEqual(context['conversation'][0]['content'],'My rent is $1000')
        self.assertEqual(json.loads(result['assumptions'][0]['value'])[0]['frequency'],'biweekly')
        self.assertNotIn('monthly_income',{f['variable'] for f in result['factors']})

    def test_http_extract_is_two_calls_and_preserves_frontend_envelope(self):
        with TestClient(app) as client,patch('gemini_gateway.call_json',side_effect=[{'model':'bill_split'},selected('amounts_owed',{'participants':4,'total_bill':120,'split_method':'equal'})]) as llm:
            response=client.post('/extract',json={'user_message':'Split $120 dinner equally among four people','reference_date':'2026-11-10','timezone':'UTC'})
        self.assertEqual(response.status_code,200);self.assertEqual(llm.call_count,2)
        self.assertIn('assumptions',response.json());self.assertIn('goal_summary',response.json())

    def test_unresolved_route_never_reaches_downstream(self):
        for route in ('gap','ambiguous','multiple'):
            with TestClient(app) as client,patch('orchestration.calculate') as downstream,patch('question_approach.calculate',return_value={'status':'conditional','answer':{'headline':'Scoped answer'}}) as scoped:
                response=client.post('/calculate',json={'original_question':'Question','assumptions':[],'extraction_meta':{'routing':{'model':route}}})
            self.assertEqual(response.status_code,200);downstream.assert_not_called()
            self.assertEqual(scoped.call_count,1 if route=='gap' else 0)

    def test_target_row_is_materialized_without_an_extra_llm_call(self):
        output=selected('projected_surplus',{'recurring_cost':90})
        output['factors']=output['factors'][:-1]
        with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},output]) as llm:
            result=e.extract('Would $90 fit?','2026-11-10','UTC')
        self.assertEqual(llm.call_count,2)
        target=next(f for f in result['factors'] if f['variable']=='projected_surplus')
        self.assertIsNone(target['value']);self.assertEqual(target['role'],'missing')
        self.assertEqual([q['target_variable'] for q in result['clarification_questions']],['monthly_surplus'])

    def test_bad_structured_shape_is_rejected_without_calculation(self):
        output=selected('monthly_surplus',{'income_entries':{'amount':900,'frequency':'biweekly'}})
        with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},output]),self.assertRaises(HTTPException):
            e.extract('My budget','2026-11-10','UTC')

    def test_existing_aliases_are_predefined_and_target_is_not_a_required_input(self):
        self.assertIn('balance',get_registry('debt_repayment').factors)
        self.assertIn('monthly_spending',get_registry('savings_goal').factors)
        self.assertIn('people',get_registry('bill_split').factors)
        output=selected('months_to_goal',{'monthly_contribution':200,'goal_amount':3000})
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},output]):
            result=e.extract('I contribute $200 monthly toward $3000. How long?','2026-11-10','UTC')
        self.assertEqual([q['target_variable'] for q in result['clarification_questions']],['current_savings'])
        self.assertNotIn('goal_deadline',{f['variable'] for f in result['factors']})


    def test_failed_factor_stage_retry_does_not_reroute(self):
        output=selected('monthly_surplus',{'monthly_income':2000})
        with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},HTTPException(502,'temporary'),output]) as llm:
            with self.assertRaises(HTTPException):e.extract('My monthly income is $2000','2026-11-10','UTC')
            result=e.extract('My monthly income is $2000','2026-11-10','UTC')
        self.assertEqual([c.kwargs['stage'] for c in llm.call_args_list],['model_routing','factor_extraction','factor_extraction'])
        self.assertEqual(result['model'],'budget_cash_flow');self.assertFalse(e.PENDING_ROUTES)

    def test_literal_duration_formatting_does_not_compute_a_result(self):
        output=selected('required_monthly_savings',{'goal_deadline':'five months'})
        output['factors'][0]['unit']='months'
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},output]):
            result=e.extract('Five months','2026-11-10','UTC')
        values={a['variable']:a['value'] for a in result['assumptions']}
        self.assertEqual(values['goal_deadline'],5)
        self.assertIsNone(values['required_monthly_savings'])

    def test_generic_totals_cannot_be_fixed_or_variable(self):
        for name in ('fixed_costs','variable_costs','fixed_income','variable_income'):
            with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},selected('monthly_surplus',{name:1650}),selected('monthly_surplus',{name:1650})]),self.assertRaises(HTTPException):
                e.extract('I earn $1650/month and spend $1650/month','2026-11-10','UTC')
        with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},selected('monthly_surplus',{'fixed_costs':1650})]):
            result=e.extract('My fixed expenses are $1650/month','2026-11-10','UTC')
        self.assertEqual(result['factors'][0]['value'],1650)

    def test_computed_known_amounts_and_percentage_conversion_are_rejected(self):
        for model,target,values,question in [
            ('bill_split','amounts_owed',{'amounts_paid':{'me':30}},'Split $120 among four people'),
            ('bill_split','amounts_owed',{'amounts_paid':{'me':'$30'}},'Split $120 among four people'),
            ('budget_cash_flow','monthly_surplus',{'spending_entries':[{'amount':30,'frequency':'monthly'}]},'Split $120 among four people'),
            ('debt_repayment','estimated_payoff_months',{'apr':0.08},'My APR is 8%'),
        ]:
            for source in ('stated','inferred'):
                output=selected(target,values);output['factors'][0]['source']=source
                with patch('gemini_gateway.call_json',side_effect=[{'model':model},copy.deepcopy(output),copy.deepcopy(output)]),self.assertRaises(HTTPException):
                    e.extract(question,'2026-11-10','UTC')

    def test_new_intent_routes_and_clears_old_factors_even_same_family(self):
        with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},selected('monthly_surplus',{'monthly_spending':1650})]):
            previous=e.extract('I spend $1650/month','2026-11-10','UTC')
        for model,target,values,message in [
            ('bill_split','amounts_owed',{'total_bill':120,'participants':4},'New question: split $120 among four people'),
            ('budget_cash_flow','monthly_surplus',{'monthly_income':3000},'New question: my income is $3000 monthly'),
        ]:
            with patch('gemini_gateway.call_json',side_effect=[{'model':model,'transition':'new'},selected(target,values)]) as llm:
                result=e.correct('old','2026-11-10','UTC',previous,message)
            self.assertEqual([c.kwargs['stage'] for c in llm.call_args_list],['model_routing','factor_extraction'])
            self.assertTrue(all(f['value'] is None for f in result['factors'] if f['variable']=='monthly_spending'),'Prior spending amount must not leak into a new intent')
            context=json.loads(llm.call_args.args[1])
            self.assertFalse(context.get('previous_factors'))
            self.assertEqual(result['model'],model)

    def test_ambiguous_transition_preserves_state_without_factor_call(self):
        with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},selected('monthly_surplus',{'monthly_spending':1650})]):
            previous=e.extract('I spend $1650/month','2026-11-10','UTC')
        with patch('gemini_gateway.call_json',return_value={'model':'ambiguous','clarification':'Is this a new question or an update?'}) as llm:
            result=e.correct('old','2026-11-10','UTC',previous,'What about dinner?')
        self.assertEqual(llm.call_count,1)
        self.assertEqual(result['factors'],previous['factors'])
        self.assertTrue(result['clarification_questions'])

    def test_followup_router_accepts_null_optional_list_but_not_invalid_branch(self):
        import model_router
        with patch('gemini_gateway.call_json',return_value={'model':'bill_split','transition':'new','models':None,'clarification':None}):
            decision=model_router.route_followup('Split dinner',current_model='budget_cash_flow',current_question='Budget',history=[])
        self.assertEqual(decision.model,'bill_split')
        with patch('gemini_gateway.call_json',return_value={'model':'bill_split','transition':'continuation'}):
            decision=model_router.route_followup('Maybe dinner',current_model='budget_cash_flow',current_question='Budget',history=[])
        self.assertEqual(decision.model,'ambiguous')

    def test_ambiguous_followup_resolution_keeps_pending_correction_evidence(self):
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},selected('required_monthly_savings',{})]):
            previous=e.extract('Savings goal','2026-11-10','UTC')
        with patch('gemini_gateway.call_json',return_value={'model':'ambiguous','clarification':'Is this an update?'}):
            pending=e.correct('Savings goal','2026-11-10','UTC',previous,'What about $1500?')
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal','transition':'continuation'},selected('required_monthly_savings',{'goal_amount':1500})]):
            result=e.correct('Savings goal','2026-11-10','UTC',pending,'An update to my existing goal')
        self.assertEqual(result['factors'][0]['value'],1500)

    def test_literal_currency_formatting_is_allowed(self):
        output=selected('monthly_surplus',{'monthly_spending':'$1,200'})
        with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},output]):
            result=e.extract('I spend $1,200 per month','2026-11-10','UTC')
        self.assertEqual(result['factors'][0]['value'],1200)

    def test_ordinary_income_and_spending_updates_skip_router(self):
        import intent_transition
        registry=get_registry('budget_cash_flow')
        for text in ('I spend $1700/month','Actually I earn $2100 monthly','monthly_income: 2200'):
            self.assertTrue(intent_transition.ordinary_update(text,registry),text)
        for text in ('New question: I spend $1700/month','Can I split $120 among four people?'):
            self.assertFalse(intent_transition.ordinary_update(text,registry),text)
