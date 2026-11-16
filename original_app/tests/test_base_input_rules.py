"""Shared causes discovered by the 16-case live baseline, not per-prompt patches."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import base_input_rules as rules
import extraction_service as extraction
import calculation_handoff as handoff
import orchestration as o
import dynamic_models as d
from factor_registry import get_registry
from test_selection_stages import selected
from test_calculation_handoff import wire


class BaseInputRules(unittest.TestCase):
    def setUp(self):o.CACHE.clear();o.PENDING_REVIEWS.clear();extraction.PENDING_ROUTES.clear()

    def test_format_normalization_keeps_amounts_and_explicit_frequency(self):
        raw=selected('projected_surplus',{'monthly_surplus':300,'recurring_cost':70,'replaced_recurring_cost':45})
        before=copy.deepcopy(raw)
        output=rules.normalize(raw,get_registry('budget_cash_flow'),'I have $300 left each month including my $45 phone plan. If I switch to a $70 plan, what remains?')
        self.assertEqual(raw,before)
        known={f['variable']:f for f in output['factors'] if f['value'] is not None}
        self.assertEqual(known['recurring_cost']['value'],70)
        self.assertEqual(known['recurring_cost']['unit'],'$/month')
        self.assertEqual(known['recurring_cost']['source'],'inferred')
        raw['factors'][1]['unit']='$/week'
        explicit=rules.normalize(raw,get_registry('budget_cash_flow'),'I have $300 left each month. The new plan is $70/week.')
        self.assertEqual(explicit['factors'][1]['unit'],'$/week')

    def test_native_collections_are_encoding_changes_not_calculations(self):
        raw={'factors':[dict(variable='amounts_paid',value={'Alex':90},unit='$'),dict(variable='participants',value=['Alex','Jamie','me'],unit='count')]}
        output=rules.normalize(raw,get_registry('bill_split'),'Alex paid $90 for everyone.')
        self.assertEqual(json.loads(output['factors'][0]['value']),{'Alex':90})
        self.assertEqual(json.loads(output['factors'][1]['value']),['Alex','Jamie','me'])
        self.assertEqual(output['factors'][1]['unit'],'text')

    def test_bare_reply_binds_only_to_backend_required_question(self):
        ex=dict(model='budget_cash_flow',target_variable='affordability_status',assumptions=[dict(variable=k,value=v,unit='$/month',source='stated',source_detail='User') for k,v in {'recurring_cost':1400,'replaced_recurring_cost':1000}.items()],factors=[])
        before=copy.deepcopy(ex)
        bound,yes=rules.bind_required_reply(ex,'Can I afford the rent change?','$500','2026-11-16','America/New_York')
        self.assertTrue(yes);self.assertEqual(ex,before)
        self.assertEqual(next(a['value'] for a in bound['assumptions'] if a['variable']=='monthly_surplus'),500)
        untouched,no=rules.bind_required_reply(ex,'Can I afford the rent change?','New question: split $120','2026-11-16','America/New_York')
        self.assertFalse(no);self.assertEqual(untouched,ex)

    def test_partial_rent_difference_exposes_support_without_inventing_baseline(self):
        req=wire('Rent change',dict(model='budget_cash_flow',target_variable='affordability_status',assumptions=[dict(variable=k,value=v,unit='$/month',source='stated',source_detail='User') for k,v in {'recurring_cost':1400,'replaced_recurring_cost':1000}.items()]))
        with patch.object(o,'call_json') as llm:response=o.calculate(req)
        llm.assert_not_called();self.assertEqual(response['status'],'needs_input')
        self.assertEqual(response['inferred_information'][0]['value'],400)
        self.assertEqual(len(response['missing_inputs']),1)
        self.assertEqual(len(response['inferred_information'][0]['supporting_facts']),2)

    def test_today_requires_no_contribution_and_verifies_shortfall(self):
        question='I have $750 set aside for a laptop that costs $900. Can I buy it today?'
        output=selected('affordability_status',dict(available_savings=750,goal_amount=900))
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},output]):ex=extraction.extract(question,'2026-11-16','America/New_York')
        req=wire(question,ex);selection,missing=handoff.resolve(req,o._facts(req))
        self.assertIsNone(missing);plan=selection['input_plan']
        self.assertEqual(plan['inputs']['months'],0);self.assertNotIn('monthly_savings',plan['inputs'])
        draft={**plan,'model':'savings_goal','target_variable':'affordability_status','factors':[dict(variable='affordability_status',value='No',unit='text',role='derived',source='inferred',source_detail='Calculated')]}
        d.validate(draft,o._facts(req));self.assertEqual(d.verify(draft)['shortfall'],'150.00')

    def test_weekly_schedule_is_coverage_not_missing(self):
        facts=dict(current_savings=100,contribution_entries=json.dumps([dict(amount=60,frequency='weekly',count=8)]))
        req=wire('Weekly deposits',dict(model='savings_goal',target_variable='projected_savings',assumptions=[dict(variable=k,value=v,unit=None,source='stated',source_detail='User') for k,v in facts.items()]))
        with patch.object(o,'call_json') as llm:response=o.calculate(req)
        llm.assert_not_called();self.assertEqual(response['status'],'unsupported')
        self.assertTrue(response['coverage_gaps']);self.assertEqual(response.get('missing_inputs',[]),[])

    def test_partial_expenses_and_unknown_apr_stay_missing(self):
        for model,target,values,expected in [('budget_cash_flow','monthly_surplus',dict(monthly_income=2000,expense_categories='[{"name":"insurance","amount":150}]'),'monthly_spending'),('debt_repayment','estimated_payoff_months',dict(principal_balance=5000,monthly_payment=200),'apr')]:
            req=wire('Question',dict(model=model,target_variable=target,assumptions=[dict(variable=k,value=v,unit=None,source='stated',source_detail='User') for k,v in values.items()]))
            _,response=handoff.resolve(req,o._facts(req))
            self.assertEqual(response['missing_inputs'][0]['variable'],expected)

    def test_quote_source_relocation_requires_verbatim_user_text(self):
        raw={'factors':[dict(variable='monthly_surplus',value=500,unit='$/month',evidence={'source':'question','quote':'$500'})]}
        output=rules.normalize(raw,get_registry('budget_cash_flow'),'What about rent?','$500')
        self.assertEqual(output['factors'][0]['evidence']['source'],'correction')
        raw['factors'][0]['evidence']['quote']='$600'
        unchanged=rules.normalize(raw,get_registry('budget_cash_flow'),'What about rent?','$500')
        self.assertEqual(unchanged['factors'][0]['evidence']['quote'],'$600')
        self.assertEqual(unchanged['factors'][0]['evidence']['source'],'question')

    def test_itemized_partial_expense_cannot_satisfy_complete_spending(self):
        q='I take home $2000 a month. Car insurance is $150 a month. What remains after all expenses?'
        assumptions=[dict(variable='monthly_income',value=2000,unit='$/month',source='stated',source_detail='I take home $2000 a month'),dict(variable='spending_entries',value='[{"amount":150,"frequency":"monthly"}]',unit='text',source='stated',source_detail='Car insurance is $150 a month')]
        req=wire(q,dict(model='budget_cash_flow',target_variable='monthly_surplus',assumptions=assumptions))
        with patch.object(o,'call_json') as llm:r=o.calculate(req)
        llm.assert_not_called();self.assertEqual(r['missing_inputs'][0]['variable'],'monthly_spending')
        self.assertNotIn('monthly_surplus',[f['variable'] for f in r.get('inferred_information',[])])

    def test_structured_main_factors_normalize_only_encoding(self):
        draft={'factors':[dict(variable='amounts_owed',value={'Maya':12,'me':18},role='derived',source='inferred')],'inputs':{'people':['Maya','me']}}
        before=copy.deepcopy(draft);output=rules.normalize_draft(draft)
        self.assertEqual(draft,before)
        self.assertEqual(json.loads(output['factors'][0]['value']),{'Maya':12,'me':18})
        self.assertEqual(output['inputs'],draft['inputs'])

    def test_itemized_method_needs_assignments_not_different_orders(self):
        for question,valid in [('Maya and I split a pizza. I also had a drink that she did not share.',True),('We ordered different things.',False)]:
            output=selected('amounts_owed',{'split_method':'itemized'})
            if valid:
                with patch('gemini_gateway.call_json',side_effect=[{'model':'bill_split'},output]):ex=extraction.extract(question,'2026-11-16','America/New_York')
                self.assertEqual(ex['assumptions'][0]['source'],'inferred')
            else:
                with patch('gemini_gateway.call_json',side_effect=[{'model':'bill_split'},copy.deepcopy(output),copy.deepcopy(output)]):
                    from fastapi import HTTPException
                    with self.assertRaises(HTTPException):extraction.extract(question,'2026-11-16','America/New_York')

if __name__=='__main__':unittest.main()
