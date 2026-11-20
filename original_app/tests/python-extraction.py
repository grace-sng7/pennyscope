"""HTTP regression tests for the new two-stage selection path, without API calls."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend_reference'))
sys.path.insert(0,str(ROOT/'tests'))
from legacy_main import app
from test_selection_stages import selected


class ExtractionIntegration(unittest.TestCase):
    def setUp(self):
        self.client=TestClient(app)
        self.request={'user_message':'I have $200 toward a $1200 goal in five months. What should I save monthly?',
                      'reference_date':'2026-11-10','timezone':'America/New_York'}
        self.selection=selected('required_monthly_savings',{'current_savings':200,'goal_amount':1200,'goal_deadline':5})

    def test_extract_route_two_calls_and_legacy_fields(self):
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},self.selection]) as llm:
            r=self.client.post('/extract',json=self.request)
        self.assertEqual(r.status_code,200);self.assertEqual(llm.call_count,2)
        self.assertEqual(r.json()['model'],'savings_goal')
        for key in ('assumptions','clarification_questions','goal_summary','confidence_note','factors'):self.assertIn(key,r.json())

    def test_bad_request_never_calls_model(self):
        with patch('gemini_gateway.call_json') as llm:r=self.client.post('/extract',json={'user_message':'Missing date'})
        self.assertEqual(r.status_code,422);llm.assert_not_called()

    def test_correct_route_preserves_selection_and_updates_values(self):
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},self.selection]):previous=self.client.post('/extract',json=self.request).json()
        corrected=selected('required_monthly_savings',{'goal_amount':1500})
        with patch('gemini_gateway.call_json',return_value=corrected) as llm:
            r=self.client.post('/correct',json={**self.request,'previous_extraction':previous,'user_correction':'Goal is actually $1500'})
        self.assertEqual(r.status_code,200);self.assertEqual(llm.call_count,1)
        self.assertEqual(llm.call_args.kwargs['stage'],'factor_extraction')
        values={a['variable']:a['value'] for a in r.json()['assumptions']}
        self.assertEqual(values['current_savings'],200);self.assertEqual(values['goal_amount'],1500)

    def test_gap_stops_before_extraction(self):
        with patch('gemini_gateway.call_json',return_value={'model':'gap'}) as llm:r=self.client.post('/extract',json=self.request)
        self.assertEqual(r.status_code,200);self.assertEqual(llm.call_count,1)
        self.assertEqual(r.json()['routing']['model'],'gap')

    def test_invalid_factor_does_not_reach_frontend(self):
        invalid=selected('apr',{})
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},invalid]), patch('gemini_gateway.call_text',return_value='ANSWER: You need to save $200 per month.') as fallback:
            r=self.client.post('/extract',json=self.request)
        self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['assumptions'],[])
        self.assertEqual(r.json()['chat_fallback']['text'],'You need to save $200 per month.')
        fallback.assert_called_once()

    def test_missing_credentials_fail_before_provider(self):
        import gemini_gateway as g
        with patch.dict('os.environ',{},clear=True),patch.object(Path,'read_text',return_value='{"api_key":""}'),patch.object(g.httpx,'post') as provider:
            with self.assertRaises(Exception) as error:g.call_json('router','question',stage='model_routing')
        self.assertEqual(error.exception.status_code,502);provider.assert_not_called()

if __name__=='__main__':unittest.main()
