"""Fault injection for bounded, stage-local retries. No live credentials/quota."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import HTTPException
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend_reference'))
import gemini_gateway as g
import orchestration as o
from test_orchestration import request, draft, review


def response(status, data=None, headers=None):
    body = {'candidates': [{'content': {'parts': [{'text': json.dumps(data or {'ok': True})}]}}]}
    return httpx.Response(status, json=body, headers=headers,
                          request=httpx.Request('POST', 'https://example.invalid'))


class RetryChecks(unittest.TestCase):
    def setUp(self):
        o.CACHE.clear(); o.PENDING_REVIEWS.clear()
        self.settings = patch.object(Path, 'read_text', return_value='{"api_key":"test-secret","model_id":"gemini/test"}')
        self.settings.start(); self.addCleanup(self.settings.stop)
        self.sleep = patch.object(g.time, 'sleep').start()
        self.addCleanup(patch.stopall)
        patch.object(g.random, 'uniform', side_effect=lambda low, high: high).start()

    def test_503_429_exponential_jitter_and_identical_snapshot(self):
        with patch.object(g.httpx, 'post', side_effect=[response(503), response(429), response(200)]) as post, self.assertLogs(g.LOGGER, level='INFO') as logs:
            self.assertEqual(g.call_json('system', 'unchanged evidence', stage='main_calculation'), {'ok': True})
        self.assertEqual(post.call_count, 3)
        self.assertEqual([c.args[0] for c in self.sleep.call_args_list], [.75, 1.5])
        bodies=[c.kwargs['json'] for c in post.call_args_list]
        self.assertEqual(bodies[0], bodies[1]); self.assertEqual(bodies[1], bodies[2])
        self.assertTrue(all('stage=main_calculation' in line for line in logs.output))
        self.assertNotIn('test-secret', '\n'.join(logs.output))
        self.assertNotIn('unchanged evidence', '\n'.join(logs.output))

    def test_timeout_retries_failed_stage(self):
        with patch.object(g.httpx, 'post', side_effect=[httpx.ReadTimeout('private provider text'), response(200)]) as post:
            g.call_json('system','prompt',stage='inspector')
        self.assertEqual(post.call_count,2);self.sleep.assert_called_once()

    def test_attempts_bounded_and_exhaustion_labeled(self):
        with patch.object(g.httpx,'post',return_value=response(503)) as post,self.assertRaises(HTTPException) as error:
            g.call_json('system','prompt',stage='inspector')
        self.assertEqual(post.call_count,3);self.assertEqual(self.sleep.call_count,2)
        self.assertIn('Inspector',error.exception.detail)

    def test_nontransient_errors_never_retry(self):
        for status in (400,401,403,404,422):
            with patch.object(g.httpx,'post',return_value=response(status)) as post,self.assertRaises(HTTPException):
                g.call_json('system','prompt')
            self.assertEqual(post.call_count,1)
        self.sleep.assert_not_called()

    def test_malformed_output_never_transport_retried(self):
        r=httpx.Response(200,json={'candidates':[]},request=httpx.Request('POST','https://example.invalid'))
        with patch.object(g.httpx,'post',return_value=r) as post,self.assertRaises(HTTPException):g.call_json('s','p')
        self.assertEqual(post.call_count,1);self.sleep.assert_not_called()

    def test_retry_after_honored_and_long_delay_not_shortened(self):
        with patch.object(g.httpx,'post',side_effect=[response(429,headers={'retry-after':'2'}),response(200)]):g.call_json('s','p')
        self.sleep.assert_called_once_with(2)
        self.sleep.reset_mock()
        with patch.object(g.httpx,'post',return_value=response(429,headers={'retry-after':str(g.STAGE_BUDGET+1)})) as post,self.assertRaises(HTTPException):g.call_json('s','p')
        self.assertEqual(post.call_count,1);self.sleep.assert_not_called()

    def test_jitter_range_and_cap(self):
        # Deterministic upper-jitter test above checks the actual exponential waits.
        self.assertLessEqual(g.BASE_DELAY * 2, g.MAX_DELAY)
        with patch.object(g.random,'uniform',return_value=.4) as jitter,patch.object(g.httpx,'post',side_effect=[response(503),response(200)]):g.call_json('s','p')
        jitter.assert_called_once_with(.375,.75);self.sleep.assert_called_once_with(.4)

    def test_deadline_stops_further_requests(self):
        clock=[0.0]
        def fail(*args,**kwargs):
            clock[0]=g.STAGE_BUDGET
            raise httpx.ReadTimeout('timeout')
        with patch.object(g.time,'monotonic',side_effect=lambda:clock[0]),patch.object(g.httpx,'post',side_effect=fail) as post,self.assertRaises(HTTPException):g.call_json('s','p')
        self.assertEqual(post.call_count,1);self.sleep.assert_not_called()

    def test_inspector_resume_preserves_main_and_corrections(self):
        req=request();req['answers']=[{'target_variable':'x','question':'Correction?','answer':'Keep my savings protected'}]
        before=copy.deepcopy(req)
        with patch.object(o,'call_json',g.call_json),patch.object(g.httpx,'post',side_effect=[response(200,draft()),response(503),response(503),response(503),response(200,review())]) as post,patch.object(o,'_verify',wraps=o._verify) as verify:
            with self.assertRaises(HTTPException):o.calculate(req)
            self.assertEqual(post.call_count,4);self.assertEqual(verify.call_count,1)
            self.assertFalse(o.CACHE);self.assertEqual(len(o.PENDING_REVIEWS),1)
            r=o.calculate(req)
            self.assertEqual(r['status'],'conditional');self.assertEqual(post.call_count,5)
            self.assertEqual(verify.call_count,1)
            bodies=[call.kwargs['json'] for call in post.call_args_list]
            self.assertEqual(bodies[1:], [bodies[1]] * 4)
        self.assertEqual(req,before);self.assertFalse(o.PENDING_REVIEWS)

    def test_changed_facts_never_resume_old_inspector(self):
        with patch.object(o,'call_json',side_effect=[draft(),HTTPException(502,'down'),{'model':'gap','gap_reason':'changed'}]) as llm:
            with self.assertRaises(HTTPException):o.calculate(request())
            req=request();req['assumptions'][0]['value']=2000
            self.assertEqual(o.calculate(req)['status'],'unsupported')
        self.assertEqual(llm.call_args.kwargs['stage'],'main_calculation')

    def test_extraction_and_correction_stage_labels(self):
        import extraction_service as e
        from test_selection_stages import selected
        valid=selected('months_to_goal',{})
        with patch.object(g,'call_json',side_effect=[{'model':'savings_goal'},valid,valid]) as llm:
            previous=e.extract('question','2026-11-10','America/New_York')
            self.assertEqual([c.kwargs['stage'] for c in llm.call_args_list],['model_routing','factor_extraction'])
            e.correct('question','2026-11-10','America/New_York',previous,'goal_amount: 1200')
            self.assertEqual(llm.call_args.kwargs['stage'],'factor_extraction')
            self.assertEqual(llm.call_count,3)


class RouteRetryChecks(unittest.TestCase):
    setUp = RetryChecks.setUp
    # Exercise the existing HTTP contract and state across an exhausted stage.
    def test_http_retry_resumes_inspector_with_same_request(self):
        from fastapi.testclient import TestClient
        from legacy_main import app
        req=request();before=copy.deepcopy(req)
        with TestClient(app) as client,patch.object(o,'call_json',g.call_json),patch('chat_fallback.respond',return_value={'kind':'limitation','text':'The supplied information is retained while the review is unavailable.'}),patch.object(g.httpx,'post',side_effect=[response(200,draft()),response(503),response(503),response(503),response(200,review())]) as post:
            failed=client.post('/calculate',json=req)
            self.assertEqual(failed.status_code,200)
            self.assertEqual(failed.json()['chat_fallback']['kind'],'limitation')
            self.assertIsNone(failed.json()['answer'])
            result=client.post('/calculate',json=req)
            self.assertEqual(result.status_code,200)
            self.assertEqual(post.call_count,5)
            self.assertEqual(result.json()['status'],'conditional')
        self.assertEqual(req,before)


class LongerTimeout(unittest.TestCase):
    def test_generation_has_sixty_seconds(self):
        with patch.object(Path,'read_text',return_value='{"api_key":"test-only"}'),patch.object(g.httpx,'post',return_value=response(200)) as post:
            g.call_json('system','prompt')
        timeout=post.call_args.kwargs['timeout']
        self.assertEqual(timeout.read,60)
        self.assertEqual(timeout.connect,5)
        self.assertGreaterEqual(g.STAGE_BUDGET,3*g.READ_TIMEOUT)
