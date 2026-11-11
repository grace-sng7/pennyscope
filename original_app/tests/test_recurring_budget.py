"""Recurring-cost routing regressions, including the reported gym question."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import orchestration as o
import dynamic_models as d
import extraction_service as extraction
from contract import ExtractionResponse

QUESTION='I get $900 every two weeks after tax, and my bills and usual spending add up to about $1,650 a month. Would a $90 monthly gym membership fit into my budget?'


def fixture(frequency='biweekly',cost=90):
    assumptions=[dict(variable='income_entries',value=json.dumps([{'amount':900,'frequency':frequency,'category':'fixed'}]),unit='text',source='stated',source_detail='User gave income and pay frequency'),
        dict(variable='monthly_expenses',value=1650,unit='$/month',source='inferred',source_detail='User said about $1650 monthly'),
        dict(variable='recurring_cost',value=cost,unit='$/month',source='stated',source_detail='Proposed new membership')]
    factors=[dict(**a,role='known',relevant=True) for a in assumptions]
    factors.extend(dict(variable=k,value=0,unit='$/month',source='inferred',source_detail='Main calculation',role='derived',relevant=True) for k in ('monthly_income','monthly_surplus','projected_surplus'))
    draft={'model':'budget_cash_flow','target_variable':'projected_surplus',
        'inputs':{'income_entries':json.loads(assumptions[0]['value']),'monthly_spending':1650,'spending_change':cost},
        'bindings':{'income_entries':'income_entries','monthly_spending':'monthly_expenses','spending_change':'recurring_cost'},
        'factors':factors,'results':{'scenario_monthly_surplus':210},'headline':'Fits ongoing budget','calculation':'Normalize income then subtract spending and new monthly charge.'}
    request={'original_question':QUESTION,'assumptions':assumptions,'extra_inputs':{},'answers':[],'parameters':{},'extraction_meta':{}}
    return draft,request


class RecurringBudget(unittest.TestCase):
    def setUp(self):o.CACHE.clear();o.PENDING_REVIEWS.clear()

    def test_reported_gym_example_without_savings_or_deadline(self):
        draft,req=fixture()
        with patch.object(o,'call_json',side_effect=[draft,{'decision':'approved','headline':'The recurring membership fits the stated budget.','detail':'This assumes usual spending excludes the proposed membership.','assumptions':['Income and spending remain constant.']}]) as llm:
            r=o.calculate(req)
        self.assertEqual(llm.call_count,2)
        values={f['variable']:f['value'] for f in r['factors']}
        self.assertEqual(values['monthly_income'],1950)
        self.assertEqual(values['monthly_surplus'],300)
        self.assertEqual(values['projected_surplus'],210)
        self.assertNotIn('current_savings',values);self.assertNotIn('goal_deadline',values)
        self.assertEqual(r['model'],'budget_cash_flow')

    def test_semimonthly_is_not_biweekly(self):
        draft,req=fixture('semimonthly')
        d.validate(draft,o._facts(req))
        r=d.verify(draft)
        self.assertEqual(r['monthly_income'],'1800.00')
        self.assertEqual(r['scenario_monthly_surplus'],'60.00')

    def test_weekly_new_cost_and_deficit(self):
        draft,req=fixture()
        draft['inputs'].pop('spending_change');draft['bindings'].pop('spending_change')
        entries=[{'amount':100,'frequency':'weekly'}]
        draft['inputs']['spending_change_entries']=entries
        draft['bindings']['spending_change_entries']='spending_change_entries'
        req['assumptions'].append(dict(variable='spending_change_entries',value=json.dumps(entries),unit='text',source='stated',source_detail='Proposed $100 weekly cost'))
        d.validate(draft,o._facts(req));r=d.verify(draft)
        self.assertEqual(r['scenario_monthly_surplus'],'-133.33')
        self.assertFalse(r['affordable'])

    def test_cannot_double_count_raw_and_monthly_changes(self):
        draft,_=fixture();draft['inputs']['spending_change_entries']=[{'amount':90,'frequency':'monthly'}]
        with self.assertRaises(ValueError):d.verify(draft)

    def test_recurring_rate_cannot_be_savings_target(self):
        raw={'assumptions':[dict(variable='goal_amount',value=90,unit='$/month',source='stated',source_detail='monthly gym')],
             'model':'savings_goal','clarification_questions':[],'goal_summary':'Membership','confidence_note':'Test'}
        with self.assertRaises(ValueError):ExtractionResponse.model_validate(raw)

    def test_live_prompt_has_no_obsolete_always_savings_rules(self):
        from test_selection_stages import selected
        output=selected('projected_surplus',{'recurring_cost':90})
        with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},output]) as llm:
            extraction.extract(QUESTION,'2026-11-10','America/New_York')
        factor_prompt=llm.call_args.args[0]
        self.assertNotIn('Always output ALL',factor_prompt)
        self.assertNotIn('savings_goal',factor_prompt)
        self.assertEqual([c.kwargs['stage'] for c in llm.call_args_list],['model_routing','factor_extraction'])

    def test_unused_inspector_numeric_headline_does_not_block_verified_result(self):
        draft,req=fixture()
        inspector={'decision':'approved','headline':'The $90 membership fits.','detail':'Incorrect unverified prose: $9999 remains.','assumptions':['The membership is an additional recurring charge.']}
        with patch.object(o,'call_json',side_effect=[draft,inspector]):r=o.calculate(req)
        self.assertIn('$210.00',r['answer']['headline'])
        self.assertNotIn('9999',r['answer']['detail'])
