"""Reported apartment prompt: partial rent evidence and replacement arithmetic."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import extraction_service as e
import orchestration as o
from test_selection_stages import selected
from test_dynamic_models import scenario
from test_calculation_handoff import wire, APPROVED

QUESTION='I want to move to a $1,400/month apartment in February, I currently pay $1,000 rent. Can I swing it?'


def rent_factors():
    result=selected('affordability_status',dict(recurring_cost=1400,replaced_recurring_cost=1000))
    for f in result['factors']:
        if f['value'] is not None:f['unit']='$/month'
    return result


class RentReplacement(unittest.TestCase):
    def setUp(self):
        e.PENDING_ROUTES.clear();o.CACHE.clear();o.PENDING_REVIEWS.clear()

    def test_reported_wrong_fixed_total_is_repaired_once_without_rerouting(self):
        bad=selected('affordability_status',dict(recurring_cost=1400,fixed_costs=1000))
        before=copy.deepcopy(bad)
        with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},bad,rent_factors()]) as llm:
            ex=e.extract(QUESTION,'2026-11-16','America/New_York')
        self.assertEqual([c.kwargs['stage'] for c in llm.call_args_list],['model_routing','factor_extraction','factor_extraction'])
        self.assertIn('validation_feedback',json.loads(llm.call_args_list[-1].args[1]))
        facts={a['variable']:a['value'] for a in ex['assumptions']}
        self.assertEqual(facts['replaced_recurring_cost'],1000)
        self.assertEqual(facts['recurring_cost'],1400)
        self.assertNotIn('fixed_costs',facts);self.assertNotIn('monthly_spending',facts)
        self.assertEqual(bad,before)
        with patch.object(o,'call_json') as main:result=o.calculate(wire(QUESTION,ex))
        main.assert_not_called();self.assertEqual(result['status'],'needs_input')
        self.assertEqual(len(result['missing_inputs']),1)
        self.assertEqual(result['missing_inputs'][0]['variable'],'monthly_surplus')

    def test_repair_cannot_bypass_evidence_guard_or_loop(self):
        bad=selected('affordability_status',dict(recurring_cost=1400,fixed_costs=1000))
        with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},bad,copy.deepcopy(bad)]) as llm:
            with self.assertRaises(HTTPException):e.extract(QUESTION,'2026-11-16','America/New_York')
        self.assertEqual(llm.call_count,3)
        self.assertTrue(e.PENDING_ROUTES) # a manual retry retains the Router result

    def test_starting_surplus_includes_old_rent_so_only_difference_is_applied(self):
        with patch('gemini_gateway.call_json',side_effect=[{'model':'budget_cash_flow'},rent_factors()]):
            ex=e.extract(QUESTION,'2026-11-16','America/New_York')
        req=wire(QUESTION,ex);req['extra_inputs']={'monthly_surplus':700}
        draft,_=scenario('budget_cash_flow',dict(monthly_surplus=700,spending_change=1400,replaced_recurring_cost=1000),
                         'affordability_status','text',dict(monthly_surplus='monthly_surplus',spending_change='recurring_cost',replaced_recurring_cost='replaced_recurring_cost'))
        draft['results']={'monthly_surplus':700,'scenario_monthly_surplus':300,'monthly_surplus_change':-400,'affordable':True}
        with patch.object(o,'call_json',side_effect=[draft,APPROVED]):result=o.calculate(req)
        self.assertEqual(next(f['value'] for f in result['factors'] if f['variable']=='affordability_status'),'Yes')
        self.assertEqual(o._verify(draft)['scenario_monthly_surplus'],'300.00')

    def test_replacement_works_with_complete_cash_flow_and_reductions(self):
        draft,_=scenario('budget_cash_flow',dict(monthly_income=3000,monthly_spending=2300,spending_change=1400,replaced_recurring_cost=1000),'projected_surplus','$/month')
        self.assertEqual(o._verify(draft)['scenario_monthly_surplus'],'300.00')
        draft['inputs']['spending_change']=800
        self.assertEqual(o._verify(draft)['scenario_monthly_surplus'],'900.00')

    def test_replacement_requires_both_raw_amounts(self):
        draft,_=scenario('budget_cash_flow',dict(monthly_surplus=700,replaced_recurring_cost=1000),'projected_surplus','$/month')
        with self.assertRaises(ValueError):o._verify(draft)

if __name__=='__main__':unittest.main()
