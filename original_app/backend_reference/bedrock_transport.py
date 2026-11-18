"""IAM-signed Bedrock JSON transport. SDK retries are disabled.

The shared stage gateway owns transient retries. Credentials never enter prompts,
logs, browser responses, or global bearer-token environment variables.
"""
import json
import os
from pathlib import Path
import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import (ClientError, ReadTimeoutError, ConnectTimeoutError,
                                  EndpointConnectionError)


def _local_settings(path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return {}


def generate_json(system, prompt, schema, read_timeout):
    return _generate(system,prompt,schema,read_timeout,json_output=True)


def generate_text(system,prompt,read_timeout):
    return _generate(system,prompt,None,read_timeout,json_output=False)


def _generate(system, prompt, schema, read_timeout, *, json_output):
    # Production credentials come only from the server environment. Keep the
    # ignored local settings file as an optional development fallback.
    settings_path = Path(__file__).resolve().parents[2] / '.secrets/aws_iam.json'
    environment_credentials = bool(os.environ.get('AWS_ACCESS_KEY_ID') or os.environ.get('AWS_SECRET_ACCESS_KEY'))
    settings = {} if environment_credentials else _local_settings(settings_path)
    key = os.environ.get('AWS_ACCESS_KEY_ID', settings.get('aws_access_key_id', '')).strip()
    secret = os.environ.get('AWS_SECRET_ACCESS_KEY', settings.get('aws_secret_access_key', '')).strip()
    model = os.environ.get('BEDROCK_MODEL_ID', settings.get('model_id', '')).strip().removeprefix('bedrock/')
    if not key or not secret: raise ValueError('IAM credentials missing')
    if not model: raise ValueError('BEDROCK_MODEL_ID missing')
    session = boto3.Session(aws_access_key_id=key, aws_secret_access_key=secret,
        aws_session_token=os.environ.get('AWS_SESSION_TOKEN', settings.get('aws_session_token', '')).strip() or None,
        region_name=os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION') or settings.get('region', 'us-east-1'))
    config=Config(connect_timeout=5,read_timeout=read_timeout,retries={'total_max_attempts':1},
                  auth_scheme_preference='sigv4')
    client=session.client('bedrock-runtime',config=config)
    instruction=system+('\nReturn exactly one valid JSON object, with no markdown or commentary.' if json_output else '\nRespond in plain language, not JSON.')
    if schema:
        instruction+='\nYour response MUST include every required field in this JSON Schema:\n'+json.dumps(schema)
        properties=schema.get('properties',{})
        if 'factors' in properties:
            if 'inputs' in properties or 'assumptions' in properties or 'calculation' in properties:
                instruction+='\nIf target_variable is non-null, include that variable exactly once in factors.'
            if 'inputs' in properties or 'calculation' in properties:
                instruction+='\nThis is the MAIN calculation stage. Perform the primary arithmetic and return numeric results. The target factor is derived, not missing.'
            else:
                instruction+='\nThis is factor extraction only for the already-selected registry. Preserve stated values and raw frequencies. Do not calculate, select a model or decide missing-input requirements. An unsolved target is null/missing, not a question to the user.'
    try:
        result=client.converse(modelId=model,
            system=[{'text':instruction}],messages=[{'role':'user','content':[{'text':prompt}]}],
            inferenceConfig={'maxTokens':4096,'temperature':0})
    except ClientError as exc:
        code=exc.response.get('Error',{}).get('Code')
        status=exc.response.get('ResponseMetadata',{}).get('HTTPStatusCode',500)
        if code in ('ThrottlingException','TooManyRequestsException'):status=429
        if code=='ServiceUnavailableException':status=503
        headers=exc.response.get('ResponseMetadata',{}).get('HTTPHeaders',{})
        response=httpx.Response(status,headers={'retry-after':headers['retry-after']} if 'retry-after' in headers else {},
                                request=httpx.Request('POST','https://bedrock-runtime.amazonaws.com'))
        raise httpx.HTTPStatusError('Bedrock request failed',request=response.request,response=response) from None
    except ReadTimeoutError:
        raise httpx.ReadTimeout('Bedrock response timed out') from None
    except (ConnectTimeoutError,EndpointConnectionError):
        raise httpx.ConnectError('Bedrock connection failed') from None
    finally:
        client.close()
    if result.get('stopReason')=='max_tokens':raise ValueError('Incomplete model response')
    text=''.join(c.get('text','') for c in result['output']['message']['content']).strip()
    if not json_output:return text
    if text.startswith('```'):
        text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
    data=json.loads(text)
    if not isinstance(data,dict):raise ValueError('Expected JSON object')
    return data
