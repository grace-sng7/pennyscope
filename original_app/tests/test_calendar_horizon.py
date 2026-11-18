"""Calendar assumptions and complete spending must avoid redundant deposit questions."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import calendar_horizon as c
import extraction_service as e
import orchestration as o
from test_savings_breakdown import QUESTION,ENTRIES,extracted
from test_calculation_handoff import wire
from test_selection_stages import selected

class CalendarHorizon(unittest.TestCase):
    def setUp(self):o.CACHE.clear();e.PENDING_ROUTES.clear()

    def test_month_deadline_uses_reference_date_with_visible_assumption(self):
        fact=c.infer('next March','2026-11-18')
        self.assertEqual(fact['value'],4);self.assertEqual(fact['role'],'derived')
        self.assertIn('end of March 2027',fact['source_detail'])
        self.assertEqual(c.infer('2027-03-01','2026-11-18')['value'],3)
        self.assertEqual(c.infer('2027-03-31','2026-11-18')['value'],4)
        self.assertEqual(c.infer('next January','2026-11-18')['value'],2)
        for deadline in ('spring break','sometime next year','2026-01-01'):
            self.assertIsNone(c.infer(deadline,'2026-11-18'))
        self.assertIsNone(c.infer('next March',None))

    def test_laptop_complete_breakdown_reaches_main_and_budget_chart(self):
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},extracted()]):ex=e.extract(QUESTION,'2026-11-18','America/New_York')
        self.assertEqual(ex['clarification_questions'],[])
        self.assertIn('Assumes the end of March 2027.',ex['assistant_message'])
        draft=dict(model='savings_goal',target_variable='affordability_status',
            inputs=dict(solve_for='affordability',current_savings=900,monthly_income=2400,spending_entries=ENTRIES,target=2500,months=4),
            bindings=dict(current_savings='current_savings',monthly_income='monthly_income',spending_entries='spending_entries',target='goal_amount',months='contribution_months'),
            results=dict(affordability_status='Yes',monthly_expenses=1600,monthly_surplus=800,projected_savings=4100),
            factors=[dict(variable=k,value=v,unit=unit,role='derived',source='inferred',source_detail='Main arithmetic') for k,v,unit in [('affordability_status','Yes','text'),('monthly_expenses',1600,'$/month'),('monthly_surplus',800,'$/month')]],
            headline='Yes, if you set aside the $800 monthly remainder and use your available savings.',calculation='1000+600=1600; 2400-1600=800; 900+800*4=4100',assumptions=[])
        with patch.object(o,'call_json',side_effect=[draft,{'decision':'approved'}]) as main:result=o.calculate(wire(QUESTION,ex))
        self.assertEqual(main.call_count,2);self.assertEqual(result['verification']['status'],'matched')
        self.assertIn('$800',result['answer']['headline']);self.assertEqual(result.get('missing_inputs',[]),[])
        self.assertEqual(result['visuals']['budget']['expenses'],[{'label':'rent','amount':1000.0},{'label':'everything else','amount':600.0}])
        self.assertEqual(result['visuals']['timeline'][-1]['set_aside'],3200)
        self.assertIn('end of March 2027',result['narrative']['text'])

    def test_correction_recomputes_calendar_and_explicit_count_wins(self):
        response=dict(model='savings_goal',target_variable='projected_savings',selection_state={'reference_date':'2026-11-18'},assumptions=[dict(variable='goal_deadline',value='next March')],factors=[])
        first=c.annotate(response);self.assertEqual(first['assumptions'][-1]['value'],4)
        first['assumptions'][0]['value']='2027-03-01'
        second=c.annotate(first);self.assertEqual(second['assumptions'][-1]['value'],3)
        second['assumptions'][-1].update(value=2,source='stated',source_detail='User says two deposits')
        self.assertEqual(c.annotate(second)['assumptions'][-1]['value'],2)

    def test_partial_spending_still_requires_capacity(self):
        output=selected('affordability_status',dict(current_savings=900,goal_amount=2500,goal_deadline='next March',monthly_income=2400))
        next(f for f in output['factors'] if f['variable']=='goal_deadline')['unit']='text'
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},output]):ex=e.extract(QUESTION,'2026-11-18','America/New_York')
        self.assertEqual([q['target_variable'] for q in ex['clarification_questions']],['monthly_expenses'])

    def test_everything_else_amount_is_not_accepted_as_total_spending(self):
        bad=extracted(True)
        next(f for f in bad['factors'] if f['variable']=='monthly_expenses')['value']=600
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},bad,extracted()]) as llm:
            ex=e.extract(QUESTION,'2026-11-18','America/New_York')
        self.assertEqual(llm.call_count,3)
        self.assertEqual(ex['clarification_questions'],[])
        self.assertFalse(any(a['variable']=='monthly_expenses' and a['value']==600 for a in ex['assumptions']))
