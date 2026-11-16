"""Opt-in live regression batch. Exemplars are an oracle, never backend context.

Usage from repository root:
 .venv/bin/python original_app/tests/exemplar_batch.py --phase before --source /path/to.csv
Only English user prompts, the explicitly specified B3 reply, ordinary date/time
metadata and backend-generated conversation state are submitted to FastAPI.
No Worksheet expectations or answer text enter any backend/provider request.
"""
import argparse
import copy
import csv
import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[2]
BACKEND=ROOT/'original_app/backend_reference'
sys.path[:0]=[str(ROOT),str(BACKEND)]
import gemini_gateway as gateway
import orchestration as orchestration
import dynamic_models
import extraction_evidence
import calculation_handoff
from main import app

OUTPUT=ROOT/'original_app/tests/regression_artifacts'
EXPECTED={
 'B1':dict(model='budget_cash_flow',target='monthly_surplus',action='calculate',numbers={'monthly_surplus':550}),
 'B2':dict(model='budget_cash_flow',target='projected_surplus',action='calculate',numbers={'scenario_monthly_surplus':275}),
 'B3':dict(model='budget_cash_flow',target='affordability_status',action='clarify',missing=['monthly_surplus'],support={'spending_change':400},followup=dict(action='calculate',numbers={'scenario_monthly_surplus':100,'affordable':True})),
 'B4':dict(model='budget_cash_flow',target='monthly_surplus',action='clarify',missing=['monthly_spending']),
 'S1':dict(model='savings_goal',target='required_monthly_savings',action='calculate',numbers={'required_monthly_savings':200}),
 'S2':dict(model='savings_goal',target='projected_savings',action='calculate',numbers={'projected_savings':900}),
 'S3':dict(model='savings_goal',target='affordability_status',action='calculate',numbers={'shortfall':150,'affordable':False}),
 'S4':dict(model='savings_goal',target='projected_savings',action='calculate_or_gap',numbers={'projected_savings':580}),
 'BL1':dict(model='bill_split',target='amounts_owed',action='calculate',shares=[32,32,32]),
 'BL2':dict(model='bill_split',target='amounts_owed',action='calculate',shares=[12,18]),
 'BL3':dict(model='bill_split',target='settlements',action='calculate',transfers=[30,30]),
 'BL4':dict(model='bill_split',target='amounts_owed',action='clarify',missing=['split_method']),
 'D1':dict(model='debt_repayment',target='estimated_payoff_months',action='calculate',numbers={'payoff_months':6}),
 'D2':dict(model='debt_repayment',target='estimated_payoff_months',alternate_targets=['total_interest'],action='calculate',numbers={'payoff_months':2,'total_interest':15}),
 'D3':dict(model='debt_repayment',target='required_monthly_payment',action='calculate',numbers={'required_monthly_payment':150}),
 'D4':dict(model='debt_repayment',target='estimated_payoff_months',action='clarify',missing=['apr']),
}


def load_cases(source):
 with Path(source).open(newline='',encoding='utf-8-sig') as f:rows=list(csv.reader(f))
 headers=rows[3]
 cases=[]
 for row in rows[4:]:
  item=dict(zip(headers,row));case_id=item.get('ID','').strip()
  if case_id not in EXPECTED:continue
  # Parse only the specifically labeled test reply, not any example answer.
  match=re.search(r'Test reply in the same chat:\s*([^\n]+)',item['Next action'])
  followup=match.group(1).rstrip('.') if match else None
  cases.append({'id':case_id,'prompt':item['English user prompt'],'followup':followup,
                'oracle':{k:item[k] for k in headers if k not in ('English user prompt','Expected right side Worksheet','Review status','Actual result','Reviewer notes')},
                'expected':EXPECTED[case_id]})
 assert len(cases)==16 and sum(c['followup'] is not None for c in cases)==1
 assert next(c['followup'] for c in cases if c['id']=='B3')=='$500'
 return cases


def decoded(value):
 if isinstance(value,str):
  try:return json.loads(value)
  except ValueError:pass
 return value


def approx(left,right):
 if isinstance(right,bool):return left is right
 try:return abs(float(left)-float(right))<0.0051
 except (ValueError,TypeError):return left==right


def compare(case,turn):
 expected={**case['expected']}
 if turn['turn']>1:expected.update(expected['followup'])
 findings=[]
 def issue(stage,message):findings.append({'stage':stage,'message':message})
 model=turn['selected_model'];target=turn['target']
 if model!=expected['model']:issue('routing',f"Expected {expected['model']}; selected {model}.")
 target_equivalents={'required_monthly_savings':['monthly_contribution'],'monthly_contribution':['required_monthly_savings'],'months_to_goal':['goal_deadline']}
 if target not in [expected['target'],*expected.get('alternate_targets',[]),*target_equivalents.get(expected['target'],[])]:issue('target_selection',f"Expected {expected['target']}; selected {target}.")
 result=turn.get('calculation_response') or {}
 status=result.get('status');action=expected['action']
 if turn['error']:
  stage=turn.get('failure_stage') or ('extraction' if turn.get('extraction_http')!=200 else 'calculation')
  issue(stage,f"HTTP failure: {turn['error']}")
 elif action=='clarify':
  if status!='needs_input':issue('input_checks',f"Expected clarification; got {status}.")
  actual=[m['variable'] for m in turn['missing_information']]
  aliases={'monthly_expenses':'monthly_spending'}
  normalized=[aliases.get(n,n) for n in actual]
  if not set(normalized)&set(expected['missing']):issue('input_checks',f"Expected required input {expected['missing']}; asked {actual}.")
  if len(actual)!=1:issue('input_checks',f"Expected one focused question; got {len(actual)}.")
 elif action=='calculate_or_gap' and turn['coverage_gaps']:
  # An honest explicit coverage gap is acceptable; asking for supplied inputs isn't.
  if turn['missing_information']:issue('model_coverage','Coverage limit was mixed with missing inputs.')
 elif status not in ('ready','conditional'):
  issue('model_coverage' if action=='calculate_or_gap' else 'input_checks',f"Expected calculation; got {status}, required inputs {turn['missing_information']}.")
 else:
  actual=turn.get('verified_result') or {}
  for key,value in expected.get('numbers',{}).items():
   if not approx(actual.get(key),value):issue('calculation',f"Expected {key}={value}; verified {actual.get(key)}.")
  if 'shares' in expected:
   owed=actual.get('amounts_owed',{})
   if sorted(float(v) for v in owed.values())!=expected['shares']:issue('calculation',f"Expected shares {expected['shares']}; got {owed}.")
   if case['id']=='BL2':
    maya=next((v for name,v in owed.items() if 'maya' in name.lower()),None)
    if not approx(maya,12):issue('calculation','Maya must owe 12; the user-only drink must belong to the user.')
  if 'transfers' in expected:
   transfers=actual.get('transfers',[])
   if sorted(float(t['amount']) for t in transfers)!=expected['transfers'] or any(t['to'].lower()!='alex' or t['from'].lower()=='alex' for t in transfers):
    issue('calculation',f"Expected two 30 transfers to Alex; got {transfers}.")
 # Supporting results requested by the exemplar must actually be returned, not
 # merely present in Python's private verification trace.
 displayed={f['variable']:f['value'] for f in result.get('factors') or [] if f.get('role')=='derived'}
 if case['id']=='D2' and status in ('ready','conditional'):
  if not any(k in displayed for k in ('estimated_payoff_months','payoff_months')) or 'total_interest' not in displayed:
   issue('target_selection','One schedule calculated both outputs, but the response omitted one requested output (time or total interest).')
 if case['id']=='B3':
  if turn['turn']==1 and not any(approx(f.get('value'),400) for f in turn['inferred_information']):
   issue('input_checks','The prompt supports a 400/month increase, but the initial clarification response did not expose that supported calculation.')
  if turn['turn']==2 and status in ('ready','conditional') and not approx(displayed.get('projected_surplus'),100):
   issue('target_selection','The inspected response did not include the requested supporting projected surplus of 100/month.')
 if case['id']=='S4' and turn['coverage_gaps']:
  schedules=[decoded(f['value']) for f in turn['given_information'] if f['variable']=='contribution_entries']
  if not schedules or not any(e.get('frequency')=='weekly' and approx(e.get('amount'),60) and approx(e.get('count'),8) for schedule in schedules for e in schedule):
   issue('model_coverage','The coverage response did not preserve the supplied 60/week and exact eight-deposit schedule.')
 # Validate all returned roles/values and known numbers/units through production
 # validators, plus semantic rules not enforced by those validators.
 for f in result.get('factors') or []:
  if f['role']=='missing' and f['variable'] in [m['variable'] for m in turn['missing_information']] and f['variable']==target:
   issue('input_checks','The requested target was incorrectly asked as an input.')
  if f['variable']=='affordability_status' and f.get('unit') not in (None,'text'):
   issue('calculation',f"A yes/no affordability result has a currency unit: {f.get('unit')}.")
  if f['role']=='derived' and f['source']!='inferred':issue('extraction','A computed factor was labeled stated.')
  if f['variable'] in ('monthly_surplus','projected_surplus','monthly_contribution','required_monthly_savings','monthly_payment','required_monthly_payment') and f.get('unit') not in ('$/month',None):
   issue('calculation',f"Incorrect unit for {f['variable']}: {f.get('unit')}.")
  if f['variable'] in ('estimated_payoff_months','payoff_months','months_to_goal') and f.get('unit') not in ('months',None):
   issue('calculation',f"Incorrect duration unit for {f['variable']}: {f.get('unit')}.")
 return findings


def run_turn(client,case,turn_index,previous=None):
 turn={'case_id':case['id'],'turn':turn_index,'user_message':case['prompt'] if turn_index==1 else case['followup'],
       'selected_model':None,'target':None,'given_information':[],'inferred_information':[],
       'missing_information':[],'coverage_gaps':[],'result_or_next_question':None,'error':None,
       'stages':[],'backend_requests':[],'verification_runs':[],'validation_failures':[]}
 if previous is not None:turn['selected_model']=previous.get('model')
 original_call=gateway.call_json;original_verify=orchestration._verify;original_evidence=extraction_evidence.validate
 original_validate=orchestration._validate;original_mode=calculation_handoff.validate_mode
 def provider(*args,**kw):
  stage=kw.get('stage','extraction');record={'stage':stage};turn['stages'].append(record)
  try:
   output=original_call(*args,**kw);record['output']=copy.deepcopy(output);return output
  except Exception as exc:record['error_type']=type(exc).__name__;raise
 def verify(draft):
  try:
   actual=original_verify(draft);turn['verification_runs'].append({'draft':copy.deepcopy(draft),'result':copy.deepcopy(actual)});return actual
  except Exception as exc:
   turn['validation_failures'].append({'stage':'calculation','type':type(exc).__name__,'reason':str(exc)});raise
 def evidence(*args,**kw):
  try:return original_evidence(*args,**kw)
  except Exception as exc:
   turn['validation_failures'].append({'stage':'extraction','factor':args[0].variable,'value':args[0].value,'reason':str(exc)});raise
 def validate(*args,**kw):
  try:return original_validate(*args,**kw)
  except Exception as exc:
   turn['validation_failures'].append({'stage':'calculation','type':type(exc).__name__,'reason':str(exc)});raise
 def mode(*args,**kw):
  try:return original_mode(*args,**kw)
  except Exception as exc:
   turn['validation_failures'].append({'stage':'target_selection','type':type(exc).__name__,'reason':str(exc)});raise
 def post(action,payload):
  turn['backend_requests'].append({'action':action,'payload':copy.deepcopy(payload)})
  r=client.post('/'+action,json=payload)
  return r,r.json()
 with patch.object(gateway,'call_json',provider),patch.object(orchestration,'call_json',provider),patch.object(orchestration,'_verify',verify),patch.object(extraction_evidence,'validate',evidence),patch.object(orchestration,'_validate',validate),patch.object(calculation_handoff,'validate_mode',mode):
  payload=dict(user_message=case['prompt'],reference_date='2026-11-16',timezone='America/New_York')
  if turn_index>1:
   if previous is None:
    turn['error']='Follow-up blocked because initial extraction failed.';return turn,None
   payload.update(previous_extraction=previous,user_correction=case['followup'])
  response,ex=post('extract' if turn_index==1 else 'correct',payload)
  turn['extraction_http']=response.status_code
  turn['extraction_response']=ex
  if response.status_code!=200:
   turn['error']=ex.get('detail');turn['failure_stage']='extraction'
   # Capture selected model/target and rejected data as diagnostics, never as
   # accepted Given Information.
   for s in turn['stages']:
    if s['stage']=='model_routing':turn['selected_model']=s.get('output',{}).get('model')
    if s['stage']=='factor_extraction':turn['target']=s.get('output',{}).get('target_variable')
   return turn,None
  turn['selected_model']=ex.get('model');turn['target']=ex.get('target_variable')
  for f in ex.get('factors',[]):
   if f['value'] is None or not f.get('relevant',True):continue
   entry={k:f.get(k) for k in ('variable','value','unit','role','source','source_detail')}
   entry['value']=decoded(entry['value'])
   entry['supporting_facts']=[f.get('evidence') or {'detail':f.get('source_detail')}]
   turn['given_information'].append(entry)
   if f['source']=='inferred':
    turn['inferred_information'].append({**entry,'interpretation':f.get('inference') or f.get('source_detail')})
  response,result=post('calculate',dict(original_question=case['prompt'],assumptions=ex['assumptions'],extra_inputs={},answers=[],parameters={},extraction_meta={k:v for k,v in ex.items() if k not in ('assumptions','clarification_questions')}))
  turn['calculation_http']=response.status_code;turn['calculation_response']=result
  turn['resolved_model']=result.get('model') or turn['selected_model']
  turn['resolved_target']=result.get('target_variable') or turn['target']
  if response.status_code!=200:
   turn['error']=result.get('detail');turn['failure_stage']=turn['validation_failures'][-1]['stage'] if turn['validation_failures'] else 'calculation'
  else:
   turn['missing_information']=result.get('missing_inputs') or []
   if result.get('status')=='unsupported':turn['coverage_gaps']=[{'reason':result.get('message')}]
   turn['result_or_next_question']=result.get('answer') or result.get('message')
   for f in result.get('factors') or []:
    if f['role']!='derived':continue
    bindings=(turn['verification_runs'][-1]['draft'].get('bindings',{}) if turn['verification_runs'] else {})
    support=[{'factor_id':name,'value':next((a['value'] for a in ex['assumptions'] if a['variable']==name),None)} for name in dict.fromkeys(bindings.values())]
    turn['inferred_information'].append({**f,'value':decoded(f['value']),'supporting_facts':support})
   for f in result.get('inferred_information') or []:
    if not any(x['variable']==f['variable'] for x in turn['inferred_information']):turn['inferred_information'].append(f)
  if turn['verification_runs']:turn['verified_result']=turn['verification_runs'][-1]['result']
 return turn,ex


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--phase',required=True);args=parser.parse_args()
 cases=load_cases(args.source);OUTPUT.mkdir(exist_ok=True)
 target=OUTPUT/(args.phase+'.json')
 if target.exists():raise SystemExit(f'Refusing to overwrite prior run: {target}')
 sources={str(p.relative_to(ROOT)):p.read_text() for p in BACKEND.glob('*.py')}
 metadata={'phase':args.phase,'started_at':datetime.now(timezone.utc).isoformat(),'reference_date':'2026-11-16','provider':gateway.selected_provider(),'source_sha256':hashlib.sha256(Path(args.source).read_bytes()).hexdigest(),'backend_sha256':{p:hashlib.sha256(text.encode()).hexdigest() for p,text in sources.items()},'scope':'base input rules only; Worksheet excluded','cases':cases,'turns':[]}
 (OUTPUT/(args.phase+'_backend_source.json')).write_text(json.dumps(sources,indent=2))
 with TestClient(app) as client:
  for case in cases:
   orchestration.CACHE.clear();orchestration.PENDING_REVIEWS.clear()
   import extraction_service
   extraction_service.PENDING_ROUTES.clear()
   previous=None
   for index in range(1,3 if case['followup'] else 2):
    started=time.monotonic()
    try:turn,previous=run_turn(client,case,index,previous)
    except Exception as exc:
     turn={'case_id':case['id'],'turn':index,'selected_model':None,'target':None,'given_information':[],'inferred_information':[],'missing_information':[],'coverage_gaps':[],'error':f'{type(exc).__name__}: {exc}','failure_stage':'execution','stages':[]}
    turn['elapsed_seconds']=round(time.monotonic()-started,3)
    turn['differences']=compare(case,turn)
    turn['comparison']='pass' if not turn['differences'] else 'different'
    metadata['turns'].append(turn)
    target.write_text(json.dumps(metadata,indent=2,default=str))
    print(f"{case['id']} turn {index}: {turn['comparison']} | {turn['selected_model']} / {turn['target']} | {(turn.get('calculation_response') or {}).get('status',turn['error'])} | {turn['elapsed_seconds']}s",flush=True)
    for finding in turn['differences']:print('  '+finding['stage']+': '+finding['message'],flush=True)
 metadata['completed_at']=datetime.now(timezone.utc).isoformat()
 target.write_text(json.dumps(metadata,indent=2,default=str))
 print('COMPLETE',str(target),flush=True)

if __name__=='__main__':main()
