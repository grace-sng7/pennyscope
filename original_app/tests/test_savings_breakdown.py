"""Reported laptop suggestion: preserve expense literals and calendar phrases."""
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
import dynamic_models as d
from test_selection_stages import selected
from test_dynamic_models import scenario, factor
from test_calculation_handoff import wire, APPROVED

QUESTION='I make $2,400 a month after tax, rent is $1,000 and I spend about $600 on everything else. I have $900 saved. Can I afford a $2,500 laptop by next March?'
ENTRIES=[{'name':'rent','amount':1000,'frequency':'monthly'},{'name':'everything else','amount':600,'frequency':'monthly'}]


def extracted(total=False):
    values=dict(monthly_income=2400,current_savings=900,goal_amount=2500,goal_deadline='next March')
    values['monthly_expenses' if total else 'spending_entries']=1600 if total else ENTRIES
    output=selected('affordability_status',values)
    for f in output['factors']:
        if f['variable']=='monthly_income':f['unit']='$/month'
        if f['variable']=='goal_deadline':f['unit']='text'
        if f['variable']=='spending_entries':f['source']='inferred' # user said about $600
    return output


class SavingsBreakdown(unittest.TestCase):
    def setUp(self):e.PENDING_ROUTES.clear();o.CACHE.clear();o.PENDING_REVIEWS.clear()

    def test_computed_expense_total_repaired_as_literal_breakdown(self):
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},extracted(True),extracted()]) as llm:
            ex=e.extract(QUESTION,'2026-11-16','America/New_York')
        self.assertEqual(llm.call_count,3)
        facts={a['variable']:a for a in ex['assumptions']}
        self.assertNotIn('monthly_expenses',facts)
        self.assertEqual(json.loads(facts['spending_entries']['value']),ENTRIES)
        self.assertEqual(facts['goal_deadline']['value'],'next March')
        self.assertEqual(facts['spending_entries']['source'],'inferred')
        with patch.object(o,'call_json') as main:r=o.calculate(wire(QUESTION,ex))
        main.assert_not_called();self.assertEqual(len(r['missing_inputs']),1)
        self.assertEqual(r['missing_inputs'][0]['variable'],'contribution_months')

    def test_computed_totals_and_invented_durations_still_rejected(self):
        for output in [extracted(True),extracted()]:
            if 'spending_entries' in {f['variable'] for f in output['factors']}:
                next(f for f in output['factors'] if f['variable']=='goal_deadline').update(value=4,unit='months')
            with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},copy.deepcopy(output),copy.deepcopy(output)]):
                with self.assertRaises(HTTPException):e.extract(QUESTION,'2026-11-16','America/New_York')

    def test_explicit_contribution_count_resolves_text_deadline(self):
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},extracted()]):
            ex=e.extract(QUESTION,'2026-11-16','America/New_York')
        req=wire(QUESTION,ex);req['extra_inputs']['contribution_months']=4
        draft,_=scenario('savings_goal',dict(solve_for='affordability',current_savings=900,monthly_income=2400,spending_entries=ENTRIES,months=4,target=2500),
                         'affordability_status','text',dict(current_savings='current_savings',monthly_income='monthly_income',spending_entries='spending_entries',months='contribution_months',target='goal_amount'))
        draft['results']={'affordability_status':True}
        draft['factors'].extend([factor('monthly_expenses',1600,'derived','$/month'),factor('monthly_surplus',800,'derived','$/month'),factor('projected_savings',4100,'derived','$')])
        with patch.object(o,'call_json',side_effect=[draft,APPROVED]):r=o.calculate(req)
        facts={f['variable']:f['value'] for f in r['factors']}
        self.assertEqual(facts['monthly_expenses'],1600);self.assertEqual(facts['monthly_surplus'],800)
        self.assertEqual(facts['projected_savings'],4100);self.assertEqual(facts['affordability_status'],'Yes')

    def test_cannot_bind_computed_total_to_raw_entries(self):
        draft,_=scenario('savings_goal',dict(solve_for='affordability',current_savings=900,monthly_income=2400,monthly_spending=1600,months=4,target=2500),'affordability_status','text')
        facts={k:dict(value=v,unit=None) for k,v in draft['inputs'].items()}
        facts['spending_entries']=dict(value=json.dumps(ENTRIES),unit='text')
        draft['bindings']['monthly_spending']='spending_entries'
        with self.assertRaises(ValueError):d.validate(draft,facts)

    def test_null_known_total_becomes_missing_without_accepting_a_number(self):
        output=extracted()
        output['factors'].append(dict(variable='monthly_expenses',value=None,unit=None,role='known',source='inferred',source_detail='Unknown total',relevant=True))
        before=copy.deepcopy(output)
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},output]) as llm:
            ex=e.extract(QUESTION,'2026-11-16','America/New_York')
        self.assertEqual(output,before);self.assertEqual(llm.call_count,2)
        missing=next(f for f in ex['factors'] if f['variable']=='monthly_expenses')
        self.assertIsNone(missing['value']);self.assertEqual(missing['role'],'missing')
        self.assertEqual(missing['source'],'missing')

    def test_no_double_counting_expense_representations(self):
        draft,_=scenario('savings_goal',dict(solve_for='affordability',current_savings=900,monthly_income=2400,monthly_spending=1600,spending_entries=ENTRIES,months=4,target=2500),'affordability_status','text')
        with self.assertRaises(ValueError):d.verify(draft)

if __name__=='__main__':unittest.main()
