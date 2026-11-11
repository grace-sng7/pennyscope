"""Explicit opt-in live smoke test with fictional inputs (uses Gemini quota).
Run from workspace root: .venv/bin/python original_app/tests/live-flow.py
Requires frontend on 3000 and backend on 8000.
"""
import json
import time
from pathlib import Path
import httpx

BASE='http://127.0.0.1:3000/api/backend/'
question='I earn $3000 a month after tax and spend $1800 total each month. I have $2500 saved and want to keep all of it untouched. Can I save $1800 for a laptop in 6 months?'

def post(action,payload):
    r=httpx.post(BASE+action,json=payload,timeout=90)
    if r.status_code == 502:
        print('Retrying a temporary provider failure:', action, flush=True)
        r=httpx.post(BASE+action,json=payload,timeout=90)
    if r.status_code!=200:
        raise AssertionError(f'{action}: HTTP {r.status_code}; '+str(r.json().get('detail','request failed')))
    return r.json()

def req(ex):
    return {'original_question':question,'assumptions':ex['assumptions'],'extra_inputs':{},'answers':[],'parameters':{},'extraction_meta':{k:v for k,v in ex.items() if k not in ('assumptions','clarification_questions')}}

context={'user_message':question,'reference_date':'2026-11-10','timezone':'America/New_York'}
ex=post('extract',context)
assert len({a['variable'] for a in ex['assumptions']})==len(ex['assumptions'])
print('PASS live extraction with source labels',flush=True)
request=req(ex)
r=post('calculate',request)
assert r['status'] in ('ready','conditional'),r.get('message')
from decimal import Decimal
contribution=next(p['value'] for p in r['parameters'] if p['key']=='monthly_contribution')
allocation=next(p['value'] for p in r['parameters'] if p['key']=='use_from_savings')
projected=next(m['value'] for m in r['metrics'] if m['label']=='Projected at deadline')
assert Decimal(projected.replace('$','').replace(',','')) == Decimal(str(allocation))+Decimal(str(contribution))*6
assert any(m['label']=='Goal amount' and m['value']=='$1,800' for m in r['metrics'])
assert next(p for p in r['parameters'] if p['key']=='use_from_savings')['max']==0
print('PASS main draft + Python + Inspector + original response contract',flush=True)
request['parameters']={'monthly_contribution':200,'use_from_savings':0}
start=time.monotonic();r=post('calculate',request);elapsed=time.monotonic()-start
assert any(x['label']=='Projected at deadline' and x['value']=='$1,200' for x in r['metrics'])
assert 'No,' in r['answer']['headline']
assert elapsed<1,elapsed
print('PASS reviewed slider update under one second',flush=True)
corrected=post('correct',{**context,'previous_extraction':ex,'user_correction':'The laptop actually costs $1200, not $1800. Keep all other facts the same.'})
assert next(a for a in corrected['assumptions'] if a['variable']=='goal_amount')['value']==1200
assert next(a for a in corrected['assumptions'] if a['variable']=='goal_amount')['source']=='stated'
print('PASS live correction and source labels',flush=True)
r=post('calculate',req(corrected));assert r['status'] in ('ready','conditional')
assert any(x['label']=='Goal amount' and x['value']=='$1,200' for x in r['metrics'])
print('PASS correction invalidates scenario and produces newly reviewed answer',flush=True)
for path in ('/','/classic','/chat'):
    assert httpx.get('http://127.0.0.1:3000'+path,timeout=30,follow_redirects=True).status_code==200
print('PASS original screen routes serve successfully',flush=True)
