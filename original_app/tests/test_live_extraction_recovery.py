"""Regression inputs include the actual Bedrock response from the approved live audit."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import factor_selection as f
import extraction_service as e
from factor_registry import get_registry
from test_savings_breakdown import QUESTION,extracted
from test_selection_stages import selected

RAW=json.loads((Path(__file__).parent/'fixtures/bedrock-laptop-extraction.json').read_text())[0]['response']

class LiveExtractionRecovery(unittest.TestCase):
    def setUp(self):e.PENDING_ROUTES.clear()

    def test_actual_provider_category_labels_normalize_without_repair_or_fact_loss(self):
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},copy.deepcopy(RAW)]) as calls:
            ex=e.extract(QUESTION,'2026-11-18','America/New_York')
        self.assertEqual(calls.call_count,2);self.assertEqual(ex['clarification_questions'],[])
        facts={a['variable']:a['value'] for a in ex['assumptions']}
        self.assertEqual(facts['current_savings'],900);self.assertEqual(facts['goal_amount'],2500)
        self.assertEqual(facts['goal_deadline'],'next March');self.assertEqual(facts['contribution_months'],4)
        entries=json.loads(facts['spending_entries']['value']) if isinstance(facts['spending_entries'],dict) else json.loads(facts['spending_entries'])
        self.assertEqual([e['name'] for e in entries],['rent','everything else'])
        self.assertEqual([e['amount'] for e in entries],[1000,600])

    def test_bad_early_factor_does_not_drop_valid_later_facts(self):
        raw=copy.deepcopy(RAW)
        entry=next(a for a in raw['factors'] if a['variable']=='spending_entries')
        entries=json.loads(entry['value']) if isinstance(entry['value'],str) else entry['value']
        entries[0]['amount']=9999;entry['value']=json.dumps(entries)
        with patch('gemini_gateway.call_json',side_effect=[copy.deepcopy(raw),copy.deepcopy(raw)]):
            with self.assertRaises(Exception) as caught:f.select(get_registry('savings_goal'),QUESTION,reference_date='2026-11-18',timezone='America/New_York')
        kept={a['variable']:a['value'] for a in caught.exception.confirmed_factors}
        self.assertEqual(kept['current_savings'],900);self.assertEqual(kept['goal_amount'],2500)
        self.assertEqual(kept['goal_deadline'],'next March');self.assertNotIn('spending_entries',kept)

    def test_repair_keeps_confirmed_facts_when_provider_omits_them(self):
        raw=copy.deepcopy(RAW)
        wrong=copy.deepcopy(raw['factors'][0]);wrong.update(variable='monthly_contribution',value=2400)
        raw['factors'].insert(0,wrong)
        repair=copy.deepcopy(RAW);repair['factors']=[]
        with patch('gemini_gateway.call_json',side_effect=[raw,repair]):
            result=f.select(get_registry('savings_goal'),QUESTION,reference_date='2026-11-18',timezone='America/New_York')
        facts={a.variable:a.value for a in result.factors}
        self.assertEqual(facts['current_savings'],900);self.assertEqual(facts['goal_amount'],2500)
        self.assertNotIn('monthly_contribution',facts)

    def test_invented_fixed_category_still_rejected(self):
        raw=copy.deepcopy(RAW)
        entry=next(a for a in raw['factors'] if a['variable']=='spending_entries')
        entries=json.loads(entry['value']) if isinstance(entry['value'],str) else entry['value'];entries[0]['category']='fixed';entry['value']=json.dumps(entries)
        with patch('gemini_gateway.call_json',side_effect=[copy.deepcopy(raw),copy.deepcopy(raw)]):
            with self.assertRaises(Exception):f.select(get_registry('savings_goal'),QUESTION,reference_date='2026-11-18',timezone='America/New_York')

    def test_other_literal_category_labels_work_for_budget_and_income(self):
        from test_selection_stages import selected
        question='My job pays $1000 monthly. My complete monthly expenses are groceries $200 and transport $50. What is my monthly surplus?'
        raw=selected('monthly_surplus',dict(income_entries=[dict(category='job',amount=1000,frequency='monthly')],spending_entries=[dict(category='groceries',amount=200,frequency='monthly'),dict(category='transport',amount=50,frequency='monthly')]))
        with patch('gemini_gateway.call_json',return_value=raw) as calls:
            result=f.select(get_registry('budget_cash_flow'),question,reference_date='2026-11-18',timezone='America/New_York')
        self.assertEqual(calls.call_count,1)
        facts={a.variable:a.value for a in result.factors}
        self.assertEqual(json.loads(facts['income_entries'])[0]['name'],'job')
        self.assertEqual([x['name'] for x in json.loads(facts['spending_entries'])],['groceries','transport'])
