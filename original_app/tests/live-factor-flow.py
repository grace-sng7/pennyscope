"""Opt-in live factor smoke test. Fictional data; uses Gemini quota."""
import httpx
base='http://127.0.0.1:3000/api/backend/'
q='I have $500 available for a $1500 laptop goal in 4 months. How much do I need to save monthly?'
with httpx.Client(timeout=90) as client:
    e=client.post(base+'extract',json={'user_message':q,'reference_date':'2026-11-10','timezone':'America/New_York'})
    assert e.status_code==200,('extraction',e.status_code)
    extraction=e.json()
    assert extraction['model']=='savings_goal'
    r=client.post(base+'calculate',json={'original_question':q,'assumptions':extraction['assumptions'],'extra_inputs':{},'answers':[],'parameters':{},'extraction_meta':{k:v for k,v in extraction.items() if k not in ('assumptions','clarification_questions')}})
    assert r.status_code==200,('calculation',r.status_code)
    result=r.json()
    assert result['status'] in ('ready','conditional'),result['status']
    assert result['target_variable'] in ('monthly_contribution','required_monthly_savings')
    target=next(f for f in result['factors'] if f['variable']==result['target_variable'])
    assert target['role']=='derived' and float(target['value'])==250
    assert not result['parameters']
    print('PASS live original-frontend proxy → extraction → main draft → Python → Inspector → target-specific factor result')
    for route in ('/','/classic'):
        assert client.get('http://127.0.0.1:3000'+route).status_code==200
    print('PASS original screen routes')
