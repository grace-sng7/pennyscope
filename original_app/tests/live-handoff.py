"""Opt-in provider smoke test using fictional data; incurs configured API usage.
Run from repository root: .venv/bin/python original_app/tests/live-handoff.py
Tests FastAPI endpoints in process, including real Router, Extraction, Main and
Inspector. Unresolved disagreement is covered by deterministic fault injection
in test_calculation_handoff.py, not by hoping the live model disagrees.
"""
import json
import sys
from pathlib import Path
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
from legacy_main import app

client=TestClient(app)

def post(action,payload):
    response=client.post('/'+action,json=payload)
    assert response.status_code==200,(action,response.status_code)
    return response.json()

def extract(question):
    return post('extract',dict(user_message=question,reference_date='2026-11-16',timezone='America/New_York'))

def calculate(question,ex):
    return post('calculate',dict(original_question=question,assumptions=ex['assumptions'],extra_inputs={},answers=[],parameters={},
        extraction_meta={k:v for k,v in ex.items() if k not in ('assumptions','clarification_questions')}))

def target(result):
    assert result['status'] in ('ready','conditional'),(result['status'],result.get('missing_inputs'))
    return next(f['value'] for f in result['factors'] if f['variable']==result['target_variable'])

q='I have $700 left over each month after all current expenses. Would an additional $500 per month rent increase fit my budget?'
ex=extract(q)
assert ex['model']=='budget_cash_flow',ex['model']
result=calculate(q,ex)
value=target(result)
assert value==200 or result['target_variable']=='affordability_status' and value=='Yes',value
print('PASS live recurring rent / stated surplus:',result['target_variable'],value,flush=True)

q2='I have $200 saved for this goal and want $1200 in five months. How much must I save monthly?'
ex2=extract(q2);result=calculate(q2,ex2)
assert ex2['model']=='savings_goal'
assert target(result)==200,result['answer']
print('PASS live reverse savings: required monthly amount 200',flush=True)

correction='New question: split a $120 dinner bill equally among four people. How much does each owe?'
ex3=post('correct',dict(user_message=q,reference_date='2026-11-16',timezone='America/New_York',previous_extraction=ex,user_correction=correction))
assert ex3['model']=='bill_split'
assert not {'monthly_surplus','recurring_cost'} & {a['variable'] for a in ex3['assumptions']}
result=calculate(correction,ex3)
owed=json.loads(target(result))
assert len(owed)==4 and all(float(v)==30 for v in owed.values()),owed
print('PASS live budget -> bill rerouting: four shares of 30, budget facts cleared',flush=True)
