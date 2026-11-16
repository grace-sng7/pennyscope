import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import httpx
from botocore.exceptions import ClientError, ReadTimeoutError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import bedrock_transport as b
import gemini_gateway as g

SETTINGS=json.dumps({'aws_access_key_id':'fake-id','aws_secret_access_key':'fake-secret','aws_session_token':'fake-token','region':'us-east-1','model_id':'bedrock/test-model'})

class BedrockTransport(unittest.TestCase):
    def setUp(self):
        self.settings=patch.object(Path,'read_text',return_value=SETTINGS)
        self.settings.start();self.addCleanup(self.settings.stop)
        self.session=patch.object(b.boto3,'Session').start();self.addCleanup(patch.stopall)
        self.client=self.session.return_value.client.return_value
        self.client.converse.return_value={'output':{'message':{'content':[{'text':'{"ok": true}'}]}},'stopReason':'end_turn'}

    def test_iam_signing_timeout_and_no_sdk_retries(self):
        self.assertEqual(b.generate_json('system','prompt',{'type':'object'},60),{'ok':True})
        self.assertEqual(self.session.call_args.kwargs['aws_session_token'],'fake-token')
        config=self.session.return_value.client.call_args.kwargs['config']
        self.assertEqual(config.read_timeout,60)
        self.assertEqual(config.retries,{'total_max_attempts':1})
        self.assertEqual(config.auth_scheme_preference,'sigv4')
        request=self.client.converse.call_args.kwargs
        self.assertEqual(request['modelId'],'test-model')
        self.assertNotIn('fake-secret',json.dumps(request))
        self.client.close.assert_called_once()

    def test_scoped_main_schema_is_not_mislabeled_as_extraction(self):
        from question_approach import Draft
        b.generate_json('Main scoped calculation','question',Draft.model_json_schema(),60)
        instruction=self.client.converse.call_args.kwargs['system'][0]['text']
        self.assertIn('MAIN calculation stage',instruction)
        self.assertIn('include that variable exactly once',instruction)
        self.assertNotIn('factor extraction only',instruction)

    def test_throttle_is_retryable_but_access_denial_is_not(self):
        for code,status,expected in [('ThrottlingException',400,429),('AccessDeniedException',403,403)]:
            self.client.converse.side_effect=ClientError({'Error':{'Code':code,'Message':'private-provider-body'},'ResponseMetadata':{'HTTPStatusCode':status}},'Converse')
            with self.assertRaises(httpx.HTTPStatusError) as error:b.generate_json('s','p',None,60)
            self.assertEqual(error.exception.response.status_code,expected)
            self.assertNotIn('private-provider-body',str(error.exception))

    def test_timeout_translated_without_provider_details(self):
        self.client.converse.side_effect=ReadTimeoutError(endpoint_url='https://example.invalid')
        with self.assertRaises(httpx.ReadTimeout):b.generate_json('s','p',None,60)

    def test_gateway_uses_bedrock_and_retries_only_this_stage(self):
        error=httpx.HTTPStatusError('unavailable',request=httpx.Request('POST','https://example.invalid'),response=httpx.Response(503))
        with patch.object(g,'selected_provider',return_value='bedrock'),patch.object(b,'generate_json',side_effect=[error,{'ok':True}]) as generate,patch.object(g.time,'sleep'),patch.object(g.httpx,'post') as google:
            self.assertEqual(g.call_json('system','prompt',stage='inspector'),{'ok':True})
            self.assertEqual(generate.call_count,2)
            google.assert_not_called()
            self.assertEqual(generate.call_args.args[3],60)
