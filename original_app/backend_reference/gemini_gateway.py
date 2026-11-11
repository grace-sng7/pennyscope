"""Server-only JSON gateway for Gemini REST or IAM-signed Bedrock.

No Google SDK is used. HTTPX retries and Bedrock SDK retries are disabled;
this loop owns all transient stage retries. Prompts, credentials and provider bodies are never logged.
"""
import json
import logging
import os
import random
import time
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx
from fastapi import HTTPException

LOGGER = logging.getLogger(__name__)
MAX_ATTEMPTS = 3  # includes the initial request
STAGE_BUDGET = 190.0  # two calculation stages fit inside the 400s proxy timeout
READ_TIMEOUT = 60.0
PHASE_OVERHEAD = 20.0  # connect (5), write (10), pool (5)
BASE_DELAY = 0.75
MAX_DELAY = 3.0
RETRY_STATUSES = {429, 500, 502, 503, 504}
STAGES = {'extraction', 'correction', 'main_calculation', 'inspector', 'model_routing', 'factor_extraction'}



def _factor_schema(stage):
    # Additive structured-output constraint: existing envelope fields remain free.
    scalar = {'anyOf': [{'type':'number'}, {'type':'string'}, {'type':'null'}]}
    factor = {'type':'object','properties': {
        'variable':{'type':'string'},'value':scalar,
        'unit':{'anyOf':[{'type':'string'},{'type':'null'}]},
        'role':{'type':'string','enum':['known','derived','missing']},
        'source':{'type':'string','enum':['stated','inferred','missing']},
        'source_detail':{'type':'string'},'relevant':{'type':'boolean'}},
        'required':['variable','value','unit','role','source','source_detail'],
        'additionalProperties':False}
    schema = {'type':'object','properties':{
        'model':{'anyOf':[{'type':'string'},{'type':'null'}]},
        'target_variable':{'anyOf':[{'type':'string'},{'type':'null'}]},
        'factors':{'type':'array','items':factor}},
        'required':['model','target_variable','factors'],'additionalProperties':True}
    if stage in ('extraction','correction'):
        assumption = {'type':'object','properties':{k:v for k,v in factor['properties'].items() if k not in ('role','relevant')},
                      'required':['variable','value','unit','source','source_detail']}
        question = {'type':'object','properties':{k:{'type':'string'} for k in ('target_variable','question','why_it_matters')},
                    'required':['target_variable','question','why_it_matters']}
        schema['properties'].update({'assumptions':{'type':'array','items':assumption},
            'clarification_questions':{'type':'array','items':question},
            'goal_summary':{'type':'string'},'confidence_note':{'type':'string'}})
        schema['required'] += ['assumptions','clarification_questions','goal_summary','confidence_note']
    else:
        schema['properties'].update({'inputs':{'type':'object','additionalProperties':True},
            'bindings':{'type':'object','additionalProperties':{'type':'string'}},
            'results':{'type':'object','additionalProperties':True},
            'headline':{'type':'string'},'calculation':{'type':'string'},
            'assumptions':{'type':'array','items':{'type':'string'}},
            'missing_inputs':{'type':'array','items':{'type':'object','properties':{'variable':{'type':'string'},'label':{'type':'string'},'unit':{'type':'string'}},'required':['variable','label']}},
            'gap_reason':{'anyOf':[{'type':'string'},{'type':'null'}]}})
        schema['required'] += ['inputs','bindings','results','headline','calculation','assumptions','missing_inputs']
    return schema


def _retry_after(response):
    if response is None:
        return 0.0
    value = response.headers.get('retry-after')
    if not value:
        return 0.0
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 0.0
    return max(0.0, seconds) if seconds == seconds else 0.0



def selected_provider():
    override=os.environ.get('PENNYSCOPE_LLM_PROVIDER')
    if override:return override
    path=Path(__file__).resolve().parents[2]/'.secrets/llm_provider.json'
    return json.loads(path.read_text()).get('provider','gemini') if path.exists() else 'gemini'


def call_json(system, prompt, *, stage='extraction', response_schema=None):
    # Restrict log fields to known labels, not caller/provider content.
    stage = stage if stage in STAGES else 'extraction'
    call_id = uuid.uuid4().hex[:12]
    started = time.monotonic()
    deadline = started + STAGE_BUDGET
    attempt = 0
    provider = 'gemini'
    try:
        provider = selected_provider()
        if provider not in ('gemini','bedrock'):raise ValueError('Unknown provider')
        settings = json.loads((Path(__file__).resolve().parents[2] / '.secrets/gemini.json').read_text()) if provider == 'gemini' else {}
        key = os.environ.get('GEMINI_API_KEY') or settings.get('api_key')
        model = (os.environ.get('MODEL_ID') or settings.get('model_id', 'gemini/gemini-3.5-flash-lite')).removeprefix('gemini/')
        if provider == 'gemini' and not key:
            raise ValueError('missing credential')
        # Construct once: every attempt sends the same stage input snapshot.
        payload = {'systemInstruction': {'parts': [{'text': system}]},
                   'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                   'generationConfig': {'responseMimeType': 'application/json', 'temperature': 0}}
        if response_schema is not None:
            payload['generationConfig']['responseJsonSchema'] = response_schema
        elif stage in ('extraction','correction','main_calculation'):
            payload['generationConfig']['responseJsonSchema'] = _factor_schema(stage)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            remaining = deadline - time.monotonic()
            if remaining <= PHASE_OVERHEAD:
                raise TimeoutError('stage budget exhausted')
            response = None
            try:
                # Give generation up to a full minute; leave room for connection/write phases.
                if provider == 'bedrock':
                    from bedrock_transport import generate_json
                    data = generate_json(system, prompt, payload['generationConfig'].get('responseJsonSchema'),
                                         min(READ_TIMEOUT, remaining - PHASE_OVERHEAD))
                else:
                    response = httpx.post(
                        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                        headers={'x-goog-api-key': key}, json=payload,
                        timeout=httpx.Timeout(connect=5.0, read=min(READ_TIMEOUT, remaining - PHASE_OVERHEAD), write=10.0, pool=5.0),
                    )
                    response.raise_for_status()
            except (httpx.HTTPStatusError, httpx.TimeoutException, httpx.ConnectError) as exc:
                if isinstance(exc, httpx.HTTPStatusError):response = exc.response
                status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
                transient = status in RETRY_STATUSES or isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))
                if not transient or attempt == MAX_ATTEMPTS:
                    raise
                ceiling = min(MAX_DELAY, BASE_DELAY * 2 ** (attempt - 1))
                # Equal jitter ensures retries are spaced, rather than immediate.
                delay = max(random.uniform(ceiling / 2, ceiling), _retry_after(response))
                if delay + 0.1 >= deadline - time.monotonic():
                    raise  # do not ignore a long Retry-After or exceed our budget
                LOGGER.warning('llm_retry provider=%s stage=%s call=%s attempt=%d status=%s category=%s delay_s=%.3f',
                               provider, stage, call_id, attempt, status, type(exc).__name__, delay)
                time.sleep(delay)
                continue
            # Malformed output and schema errors are NOT transient transport errors.
            if provider == 'gemini':
                data = json.loads(response.json()['candidates'][0]['content']['parts'][0]['text'])
            if not isinstance(data, dict):
                raise ValueError('expected object')
            LOGGER.info('llm_success provider=%s stage=%s call=%s attempts=%d elapsed_s=%.3f',
                        provider, stage, call_id, attempt, time.monotonic() - started)
            return data
    except Exception as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        LOGGER.warning('llm_failed provider=%s stage=%s call=%s attempts=%d status=%s category=%s elapsed_s=%.3f',
                       provider, stage, call_id, attempt, status, type(exc).__name__, time.monotonic() - started)
        label = {'extraction': 'extract the facts', 'correction': 'apply your correction',
                 'main_calculation': 'draft the calculation', 'inspector': 'complete the Inspector review',
                 'model_routing': 'select a financial model', 'factor_extraction': 'extract the selected model factors'}[stage]
        raise HTTPException(status_code=502, detail=f'{"Bedrock" if provider == "bedrock" else "Gemini"} could not {label}. Your edits are preserved; please retry.') from None
