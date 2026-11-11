"""Opt-in additional model smoke tests using fictional financial data."""
import httpx
base='http://127.0.0.1:3000/api/backend/'
def post(action, payload):
    r=httpx.post(base+action,json=payload,timeout=60)
    if r.status_code==502:
        print('Retrying temporary provider failure:',action,flush=True)
        r=httpx.post(base+action,json=payload,timeout=60)
    return r

scenarios=[('budget','I earn $3000 after tax monthly and spend $1800 total per month. What is my monthly surplus?'),('bill','Split a $120 dinner bill equally among A, B, and C. Nobody has paid yet. How much does each owe?'),('debt','I owe $1000 on a loan with fixed 0% annual APR and will pay $100 monthly. How many months to repay it? No fees or new charges.')]
for name,q in scenarios:
    ex=post('extract',{'user_message':q,'reference_date':'2026-11-10','timezone':'America/New_York'})
    assert ex.status_code==200,(name,'extract',ex.status_code)
    e=ex.json()
    r=post('calculate',{'original_question':q,'assumptions':e['assumptions'],'extra_inputs':{},'answers':[],'parameters':{},'extraction_meta':{k:v for k,v in e.items() if k not in ('assumptions','clarification_questions')}})
    assert r.status_code==200,(name,'calculate',r.status_code,r.json().get('detail'))
    result=r.json();assert result['status'] in ('ready','conditional'),(name,result['status'],result.get('missing_inputs'))
    metrics=result['metrics']
    if name=='budget':assert any(m['label']=='Monthly surplus' and m['value']=='1200.00' for m in metrics)
    if name=='bill':assert len([m for m in metrics if 'Amounts owed' in m['label'] and m['value']=='40.00'])==3,metrics
    if name=='debt':assert any(m['label']=='Payoff months' and m['value']=='10' for m in metrics),metrics
    print('PASS live',name,'main + verifier + inspector',flush=True)
