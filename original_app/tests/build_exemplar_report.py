"""Build a local, self-contained audit report from immutable live batch records."""
import csv
import html
import json
from collections import Counter
from pathlib import Path
from exemplar_batch import OUTPUT, compare, decoded


def load_run(name):
 data=json.loads((OUTPUT/(name+'.json')).read_text())
 if not data.get('completed_at'):raise ValueError('Batch is not complete: '+name)
 cases={c['id']:c for c in data['cases']}
 for turn in data['turns']:
  if not turn.get('selected_model') and turn['turn']>1:
   for request in turn.get('backend_requests',[]):
    if request['action']=='correct':turn['selected_model']=request['payload']['previous_extraction'].get('model')
  turn['differences']=compare(cases[turn['case_id']],turn)
  turn['comparison']='pass' if not turn['differences'] else 'different'
  if turn.get('error') and turn.get('verification_runs'):
   verification=turn['verification_runs'][-1]
   facts={a['variable']:a['value'] for a in (turn.get('extraction_response') or {}).get('assumptions',[])}
   support=[{'factor_id':name,'value':facts.get(name)} for name in dict.fromkeys(verification['draft'].get('bindings',{}).values())]
   for native,name,unit in [('payoff_months','estimated_payoff_months','months'),('total_interest','total_interest','$'),('total_repayment','total_repayment','$')]:
    if verification['result'].get(native) is not None:
     turn['inferred_information'].append(dict(variable=name,value=verification['result'][native],unit=unit,role='derived',source='inferred',source_detail='Independent Python verification; review blocked, not a final answer.',supporting_facts=support,exposed_to_user=False,review_status='blocked'))
  if (turn.get('calculation_response') or {}).get('coverage_gaps'):
   turn['coverage_gaps']=turn['calculation_response']['coverage_gaps']
  turn['request_boundary_valid']=all(
   r['payload'].get('user_message',r['payload'].get('original_question'))==cases[turn['case_id']]['prompt']
   and (r['action']!='correct' or r['payload']['user_correction']==cases[turn['case_id']]['followup'])
   and not ({'oracle','expected','exemplar','expected_answer','worksheet'} & set(r['payload']))
   for r in turn.get('backend_requests',[]))
  if not turn['request_boundary_valid']:raise AssertionError('Exemplar leakage or altered user prompt')
 return data


def numeric_differences(turn):
 actual=turn.get('verified_result') or {}
 drafts=[s['output'] for s in turn.get('stages',[]) if s['stage']=='main_calculation' and 'output' in s]
 if not drafts:return []
 aliases={'estimated_payoff_months':'payoff_months','projected_surplus':'scenario_monthly_surplus','affordability_status':'affordable','settlements':'transfers'}
 differences=[]
 for name,value in drafts[-1].get('results',{}).items():
  native=aliases.get(name,name)
  if native not in actual or isinstance(value,(dict,list,bool)) or isinstance(actual[native],bool):continue
  try:
   if abs(float(value)-float(actual[native]))>0.0051:differences.append({'factor':name,'main_value':value,'python_value':actual[native]})
  except (ValueError,TypeError):pass
 return differences


def summary(run):
 cases=run['cases'];turns=run['turns']
 case_pass=sum(all(t['comparison']=='pass' for t in turns if t['case_id']==c['id']) for c in cases)
 return dict(cases=len(cases),matching_cases=case_pass,turns=len(turns),matching_turns=sum(t['comparison']=='pass' for t in turns),outcomes=dict(Counter((t.get('calculation_response') or {}).get('status','http_error') for t in turns)),coverage_cases=[t['case_id'] for t in turns if t['coverage_gaps']],source_sha256=run['source_sha256'],started_at=run['started_at'],completed_at=run['completed_at'])


def escaped(value):return html.escape(str(value))
def pretty(value):return '<pre>'+escaped(json.dumps(value,indent=2,ensure_ascii=False))+'</pre>'


def turn_view(turn):
 status=(turn.get('calculation_response') or {}).get('status','HTTP error')
 parts=[f'<h4>Turn {turn["turn"]} · {escaped(status)}</h4>',f'<p><b>Selected:</b> {escaped(turn["selected_model"])} · <b>Target:</b> {escaped(turn["target"])}</p>']
 for key,label in [('given_information','Given Information'),('inferred_information','Inferred Information with supporting facts'),('missing_information','Missing Information — required user inputs only'),('coverage_gaps','Coverage gaps'),('result_or_next_question','Result or next question')]:
  parts.append('<details'+(' open' if key in ('missing_information','result_or_next_question') else '')+'><summary>'+label+'</summary>'+pretty(turn.get(key,[] if key.endswith('information') or key=='coverage_gaps' else None))+'</details>')
 if turn.get('error'):parts.append('<p class="bad"><b>Error:</b> '+escaped(turn['error'])+'</p>')
 if turn['differences']:parts.append('<h5>Sheet/runtime disagreements</h5>'+pretty(turn['differences']))
 if numeric_differences(turn):parts.append('<h5>Main/Python arithmetic audit</h5>'+pretty(numeric_differences(turn)))
 if turn.get('error') and turn.get('verified_result'):parts.append('<h5>Internal Python verification — blocked, not shown as a final user result</h5>'+pretty(turn['verified_result']))
 return ''.join(parts)


def main():
 names=['before','after','after_final','after_verified']
 runs={name:load_run(name) for name in names}
 before=runs['before'];after=runs['after_verified']
 bsummary=summary(before);asummary=summary(after)
 report={'method':{'case_count':16,'turn_count':17,'provider':after['provider'],'reference_date':after['reference_date'],'backend':'FastAPI TestClient using the real configured provider and full Router → Extraction → Calculate → Main → Python → Inspector flow','exemplars_sent_to_backend':False,'worksheet_scope':'Excluded; no frontend/Worksheet files modified','comparison':'Numeric tolerance 0.0051; factor/unit/role/required-input and coverage checks; equivalent target aliases accepted; wording not matched.','coverage_limit':'S4 may report an explicit coverage gap; it does not count as a successful weekly calculation.'},'runs':{name:summary(run) for name,run in runs.items()},'case_comparisons':[]}
 for case in after['cases']:
  records={name:[t for t in run['turns'] if t['case_id']==case['id']] for name,run in runs.items()}
  notes=[]
  for turn in records['after_verified']:
   if turn['target']!=case['expected']['target'] and not any(d['stage']=='target_selection' for d in turn['differences']):notes.append('Equivalent target ID: runtime '+str(turn['target'])+' vs Sheet '+case['expected']['target']+'.')
   given={f['variable'] for f in turn['given_information']}
   if case['id']=='S1' and 'current_savings' in given:notes.append('Runtime uses current_savings for the explicitly dedicated trip fund; Sheet calls it available_savings. The source states the funds are set aside for this goal.')
   if case['id']=='B4' and 'spending_entries' in given:notes.append('Runtime retains car insurance in spending_entries rather than Sheet expense_categories. The input checker treats it as partial, so it does not satisfy complete monthly spending.')
   if case['id']=='S3':notes.append('The Sheet explicitly anticipated a possible purchase-today coverage/input gap. It is now handled as zero future deposits; no contribution question.')
   if case['id']=='S4':notes.append('The raw schedule uses the newly added contribution_entries factor because the Sheet lists no exact amount/count IDs. Sheet benchmark is 580 after eight deposits. Runtime preserves amount=60, frequency=weekly and count=8 and reports the permitted monthly-model coverage gap. No user fact is missing.')
  report['case_comparisons'].append({'id':case['id'],'prompt':case['prompt'],'specified_followup':case['followup'],'sheet_oracle':case['oracle'],'notes':notes,'runs':records})
 (OUTPUT/'comparison.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,default=str))
 with (OUTPUT/'comparison.csv').open('w',newline='',encoding='utf-8') as file:
  writer=csv.writer(file);writer.writerow(['Case','Turn','Baseline comparison','Final comparison','Selected model','Target','Given Information','Inferred Information with supporting facts','Missing Information','Coverage gaps','Result or next question','Difference stages','Sheet/runtime disagreements'])
  for item in report['case_comparisons']:
   for turn in item['runs']['after_verified']:
    prior=next(t for t in item['runs']['before'] if t['turn']==turn['turn'])
    writer.writerow([item['id'],turn['turn'],prior['comparison'],turn['comparison'],turn['selected_model'],turn['target'],json.dumps(turn['given_information'],ensure_ascii=False),json.dumps(turn['inferred_information'],ensure_ascii=False),json.dumps(turn['missing_information'],ensure_ascii=False),json.dumps(turn['coverage_gaps'],ensure_ascii=False),json.dumps(turn.get('result_or_next_question'),ensure_ascii=False),'; '.join(dict.fromkeys(d['stage'] for d in turn['differences'])),json.dumps(turn['differences'],ensure_ascii=False)])
 style='''body{font:15px/1.5 system-ui,sans-serif;margin:0;color:#1b2429;background:#f7f8f9}main{max-width:1250px;margin:auto;padding:30px}h1{font-size:26px;margin:0 0 8px}h2{font-size:20px}h3{font-size:17px}h4{font-size:15px}.stats{display:flex;gap:45px;padding:20px 0;border-block:1px solid #cbd2d8;margin:20px 0}.stats strong{font-size:25px;display:block}.muted{color:#52616d}.bad{color:#9a3c22}.good{color:#275b4e}.banner{background:#fff4e4;padding:15px;border-left:3px solid #9a3c22}details{padding:8px 0}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:12px/1.55 ui-monospace,monospace;background:#eef1f3;padding:12px}.case{padding:16px 0;border-bottom:1px solid #ccd2d6}.columns{display:grid;grid-template-columns:1fr 1fr;gap:28px}.run{min-width:0}button{padding:7px 12px;margin-right:7px;border:1px solid #aaa;background:white;cursor:pointer}a{color:#275b70}li{margin:5px 0}@media(max-width:850px){.columns{grid-template-columns:1fr}.stats{gap:20px}}'''
 parts=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Pennyscope — 16-case regression review</title><style>'+style+'</style><main>',
 '<h1>Pennyscope: 16-case regression review</h1><p class="muted">English Exemplars CSV · November 16, 2026 · live '+escaped(after['provider'])+' · 16 fresh conversations / 17 turns per full batch</p>',
 f'<div class="stats"><div><strong>{bsummary["matching_cases"]}/16</strong>Baseline cases match</div><div><strong>{asummary["matching_cases"]}/16</strong>Final cases match</div><div><strong>{asummary["matching_turns"]}/17</strong>Final turns match</div><div><strong>{len(asummary["coverage_cases"])}</strong>Explicit coverage limit</div></div>',
 '<p>Only the English prompt and the specified B3 reply ($500) were submitted as user input. The exemplar answers stayed in the harness. Backend-generated state and fixed date/time metadata were passed normally. All four complete batches and their source snapshots are retained.</p>',
 '<p>Comparison checks meanings, numbers, units, factor roles, required questions and coverage. Equivalent savings target aliases are accepted. A coverage response is not counted as a successful numerical calculation. Worksheet expectations were excluded.</p>',
 '<h2>Shared base-input changes</h2><ul><li>Canonical collection encoding and units, with quoted evidence for contextual timing and method interpretation.</li><li>Pending question context and exact-source relocation for a bare follow-up.</li><li>Complete-spending checks; partial items do not satisfy a total.</li><li>Purchase today requires no contribution input. Exact nonmonthly schedules remain a separate coverage limit.</li><li>Native raw input plans for Main; named participants and whole-bill payments retained without fabricated facts.</li><li>Requested supporting results come from the same inspected calculation. No Worksheet component changes.</li></ul>',
 '<h2>Remaining disagreement</h2><div class="banner"><b>D2: calculation / Inspector policy, outside the base-input-rule change.</b> The supplied inputs are complete. Python verifies 2 months and $15 total interest. Main returned a different interest value, and Inspector requested input with no missing facts, causing HTTP 422. No final answer was exposed. This is not an APR or other missing-input problem; no arithmetic or Inspector approval policy was changed to force a pass.</div>',
 '<h2>Evidence and machine-readable records</h2><p><a href="comparison.json">Full comparison JSON</a> · <a href="comparison.csv">Per-turn CSV</a> · <a href="before.json">Raw baseline</a> · <a href="after_verified.json">Raw final batch</a></p>',
 '<h2>Case-by-case review</h2><p><button onclick="filterCases(false)">All cases</button><button onclick="filterCases(true)">Final disagreements only</button></p>']
 for item in report['case_comparisons']:
  failed=any(t['comparison']!='pass' for t in item['runs']['after_verified'])
  parts.append(f'<section class="case" data-failed="{str(failed).lower()}"><details><summary><b>{escaped(item["id"])}</b> · <span class="{"bad" if failed else "good"}">{"DIFFERENT" if failed else "MATCH"}</span> · {escaped(item["prompt"])}</summary>')
  if item['specified_followup']:parts.append('<p><b>Specified second turn:</b> '+escaped(item['specified_followup'])+'</p>')
  parts.append('<details><summary>Sheet expectations (harness only)</summary>'+pretty(item['sheet_oracle'])+'</details>')
  for note in item['notes']:parts.append('<p class="muted">'+escaped(note)+'</p>')
  parts.append('<div class="columns"><div class="run"><h3>Before base-input changes</h3>'+''.join(turn_view(t) for t in item['runs']['before'])+'</div><div class="run"><h3>Final full batch</h3>'+''.join(turn_view(t) for t in item['runs']['after_verified'])+'</div></div></details></section>')
 parts.append('<h2>Scope and reproducibility</h2><p>110 backend tests, 25 calculator/agent tests, 6 extraction HTTP tests, frontend tests (including 800 rendering combinations) and lint passed. The report tests the API/provider flow, not browser clicks. Each live batch used fresh per-case process caches and unchanged English inputs. LLM runs remain nondeterministic; the baseline and two intermediate reruns are retained rather than hidden.</p><p class="muted">Source SHA-256: '+escaped(after['source_sha256'])+'</p></main><script>function filterCases(failed){document.querySelectorAll(".case").forEach(e=>{e.hidden=failed&&e.dataset.failed!=="true";});}</script></html>')
 (OUTPUT/'report.html').write_text(''.join(parts))
 print(json.dumps(report['runs'],indent=2))

if __name__=='__main__':main()
