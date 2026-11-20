"""The hosted screenshot's zero-month purchase must not enter savings planning."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
from fastapi.testclient import TestClient
from legacy_main import app
import extraction_service as e
import orchestration as o
import calculation_handoff as h
from test_selection_stages import selected

QUESTION='I have $750 set aside just for a laptop. The laptop costs $900 and I want to buy it today. Can I afford it with that money?'

def run_case():
    o.CACHE.clear();e.PENDING_ROUTES.clear()
    output=selected('affordability_status',dict(available_savings=750,goal_amount=900))
    with TestClient(app) as client,patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},output]):
        ex=client.post('/extract',json=dict(user_message=QUESTION,reference_date='2026-11-18',timezone='America/New_York')).json()
    req=dict(original_question=QUESTION,assumptions=ex['assumptions'],extraction_meta=ex)
    selection,missing=h.resolve(req,o._facts(req))
    assert missing is None
    draft={**selection['input_plan'], 'target_variable':'affordability_status',
        'results':{'affordability_status':'No','shortfall':150},
        'factors':[dict(variable='affordability_status',value='No',unit='text',role='derived',source='inferred',source_detail='Main: available savings are below the price.')],
        'headline':'No. You are $150 short of the $900 price.', 'calculation':'900 - 750 = 150', 'assumptions':[]}
    with TestClient(app) as client,patch.object(o,'call_json',side_effect=[draft,{'decision':'approved'}]):
        r=client.post('/calculate',json=req)
    return ex,r

class TodayPurchase(unittest.TestCase):
    def test_zero_month_purchase_goes_directly_to_main_and_card(self):
        ex,r=run_case()
        self.assertEqual(ex['clarification_questions'],[])
        self.assertFalse(any(f['role']=='missing' and f['variable']!=ex['target_variable'] and f.get('relevant',True) for f in ex['factors']))
        self.assertEqual(next(a['value'] for a in ex['assumptions'] if a['variable']=='goal_deadline'),0)
        self.assertEqual(r.status_code,200)
        result=r.json();self.assertIn(result['status'],('ready','conditional'))
        self.assertIsNotNone(result['answer']);self.assertEqual(result['verification']['status'],'matched')
        self.assertFalse(result.get('missing_inputs'))
        self.assertIn('No',result['answer']['headline'])
        self.assertIn('150',str(result))
