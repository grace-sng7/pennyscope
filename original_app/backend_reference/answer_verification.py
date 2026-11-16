"""Main owns the answer. Python verification is a target-only annotation."""
import copy
import json
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from contract import ModelFactor

KEYS={
    'projected_surplus':('projected_surplus','scenario_monthly_surplus'),
    'affordability_status':('affordability_status','affordable'),
    'monthly_contribution':('monthly_contribution','required_monthly_savings','monthly_savings'),
    'required_monthly_savings':('required_monthly_savings','monthly_contribution'),
    'months_to_goal':('months_to_goal','months_required'),
    'goal_deadline':('goal_deadline','months_required','months'),
    'estimated_payoff_months':('estimated_payoff_months','payoff_months'),
    'monthly_interest':('monthly_interest','first_month_interest'),
    'settlements':('settlements','transfers'),
}
MONTHLY={'monthly_surplus','projected_surplus','required_monthly_savings','monthly_contribution','required_monthly_payment'}
DURATIONS={'months_to_goal','goal_deadline','estimated_payoff_months'}
TEXT={'affordability_status'}


def decode(value):
    if isinstance(value,str):
        try:return json.loads(value)
        except ValueError:pass
    return value


def result_value(results,target):
    for key in KEYS.get(target,(target,)):
        if key in results and results[key] is not None:return decode(results[key])
    raise ValueError('Requested final result is unavailable')


def unit_for(target):
    return '$/month' if target in MONTHLY else 'months' if target in DURATIONS else 'text' if target in TEXT else '$'


def numeric(value):
    if isinstance(value,bool):raise ValueError('Boolean is not a numeric final answer')
    try:
        number=Decimal(str(value).replace(',','').removeprefix('$'))
    except (InvalidOperation,ValueError,TypeError):raise ValueError('Final answer is not numeric') from None
    if not number.is_finite():raise ValueError('Final answer must be finite')
    return number


def same_final(left,right,unit,path,equal_shares=False):
    left=decode(left);right=decode(right)
    if isinstance(left,bool) or isinstance(right,bool):
        convert=lambda v: {'yes':True,'no':False,'true':True,'false':False}.get(str(v).lower(),v)
        return [] if convert(left) is convert(right) else [path]
    if isinstance(left,dict) or isinstance(right,dict):
        if not isinstance(left,dict) and isinstance(right,dict) and equal_shares:
            left={key:left for key in right}
        if not isinstance(left,dict) or not isinstance(right,dict) or set(left)!=set(right):return [path]
        return [difference for key in sorted(right) for difference in same_final(left[key],right[key],unit,f'{path}.{key}')]
    if isinstance(left,list) or isinstance(right,list):
        if not isinstance(left,list) or not isinstance(right,list) or len(left)!=len(right):return [path]
        # Settlement order is not meaningful; payer, recipient and amount are.
        if all(isinstance(x,dict) and {'from','to','amount'}<=set(x) for x in left+right):
            left=sorted(left,key=lambda x:(x['from'],x['to']));right=sorted(right,key=lambda x:(x['from'],x['to']))
            return [difference for a,b in zip(left,right) for difference in (
                [path] if (a['from'],a['to'])!=(b['from'],b['to']) else same_final(a['amount'],b['amount'],unit,path))]
        return [difference for index,(a,b) in enumerate(zip(left,right)) for difference in same_final(a,b,unit,f'{path}.{index}')]
    a=numeric(left);b=numeric(right)
    if unit.startswith('$'):
        a=a.quantize(Decimal('.01'),rounding=ROUND_HALF_UP);b=b.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)
    return [] if a==b else [path]


def disagreements(proposed,actual,target=None,unit=None,equal_shares=False):
    # Compatibility for the old fixed-savings envelope, which predates target IDs.
    if target is None:
        target=next((name for name in ('projected','projected_savings','amounts_owed','payoff_months','scenario_monthly_surplus','monthly_surplus') if name in actual),None)
    if not target:raise ValueError('A requested final target is required')
    expected_unit=unit_for(target)
    unit=unit or expected_unit
    if unit!=expected_unit:raise ValueError('Final answer units cannot be compared')
    try:main_value=result_value(proposed,target)
    except ValueError:return [target]
    return same_final(main_value,result_value(actual,target),unit,target,equal_shares)


def main_response(draft,facts):
    """Validate the Main answer's structure without requiring a Python solver."""
    target=draft['target_variable']
    factors=copy.deepcopy(draft.get('factors',[]))
    selected=next((f for f in factors if f['variable']==target),None)
    results=draft.get('results') or {}
    try:value=result_value(results,target)
    except ValueError:
        if selected is None or selected.get('role')!='derived' or selected.get('value') is None:raise
        value=decode(selected['value'])
    # Recursively ensure final shares/counts/amounts are finite; text booleans
    # remain supported for the existing affordability target.
    def validate(value):
        if target=='affordability_status' and (isinstance(value,bool) or str(value).lower() in ('yes','no','true','false')):return
        if isinstance(value,dict):
            if not value:raise ValueError('Empty final shares')
            for v in value.values():validate(v)
        elif isinstance(value,list):
            for v in value:
                if target=='settlements' and isinstance(v,dict) and {'from','to','amount'}<=set(v):numeric(v['amount'])
                else:validate(v)
        else:numeric(value)
    validate(value)
    unit=(selected or {}).get('unit') or unit_for(target)
    if unit in ('boolean','bool'):unit='text'
    if target in MONTHLY and unit=='$':unit='$/month'
    if isinstance(value,(dict,list)) and unit=='text':unit=unit_for(target)
    if selected is None:
        selected=dict(variable=target,unit=unit,relevant=True);factors.append(selected)
    shown_value=('Yes' if value else 'No') if isinstance(value,bool) else json.dumps(value) if isinstance(value,(dict,list)) else value
    selected.update(value=shown_value,role='derived',source='inferred',source_detail='Calculated by Main.',unit=unit)
    names=set();valid_factors=[]
    for f in factors:
        if f['variable'] in names:continue
        if f.get('role')=='known':
            fact=facts.get(f['variable'])
            if not fact or fact.get('value') is None:continue
            f.update(value=fact['value'],unit=fact.get('unit'),source=fact['source'],source_detail=fact['source_detail'])
        elif f.get('role')=='derived':f['source_detail']='Calculated by Main.'
        try:parsed=ModelFactor.model_validate(f).model_dump()
        except (ValueError,TypeError):
            if f['variable']==target:raise
            continue
        names.add(f['variable']);valid_factors.append(parsed)
    factors=valid_factors
    def format_final(v):
        if isinstance(v,dict):return '; '.join(str(k)+': '+format_final(amount) for k,amount in v.items())
        if isinstance(v,list):
            if target=='settlements':return '; '.join(str(t['from'])+' pays '+str(t['to'])+' '+format_final(t['amount']) for t in v) or 'No transfers needed.'
            return '; '.join(format_final(amount) for amount in v)
        if isinstance(v,bool):return 'Yes' if v else 'No'
        if unit.startswith('$'):return '$'+format(numeric(v).quantize(Decimal('.01'),rounding=ROUND_HALF_UP),',.2f')+(' / month' if unit=='$/month' else '')
        return str(v)+(' '+unit if unit not in ('text','') else '')
    headline=target.replace('_',' ').capitalize()+': '+format_final(value)
    response=dict(status='conditional',model=draft['model'],target_variable=target,factors=factors,
                  answer={'headline':headline},parameters=[],metrics=[],explanations=[],
                  assumptions=[{'text':s} for s in draft.get('assumptions',[]) if isinstance(s,str)],
                  limitations=['The answer is calculated by Main; independent verification is advisory.'])
    if isinstance(draft.get('headline'),str) and draft['headline'].strip():response['answer']['detail']=draft['headline']
    if draft.get('calculation'):response['explanations']=[{'label':'Main calculation','text':draft['calculation']}]
    return response,value,unit
