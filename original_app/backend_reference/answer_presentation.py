"""Optional Grace-style presentation of the selected answer, never a solver/router.

Visual breakdowns are enabled only when the existing target-only check matches
Main. They reuse that calculation's raw inputs and checked supporting values.
No presentation failure, missing chart input or scenario can change Main's answer.
Adapted from Grace 086b79b's funding/budget/timeline/options presentation.
"""
import copy
import math
import re
from decimal import Decimal, ROUND_HALF_UP


def num(value):
    if isinstance(value,bool):raise ValueError('Not an amount')
    n=Decimal(str(value))
    if not n.is_finite():raise ValueError('Not finite')
    return n


def rounded(value):return float(num(value).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
def money(value):
    n=rounded(value)
    sign='-' if n<0 else '';n=abs(n)
    return sign+(f'${n:,.0f}' if n==int(n) else f'${n:,.2f}')


def budget(income,spending,contribution,entries=None,basis='income'):
    expenses=[]
    if entries:
        # Raw nonmonthly categories stay out of a monthly plot; use the verified
        # complete monthly total instead of quietly treating raw values as monthly.
        if all(e.get('frequency','monthly')=='monthly' for e in entries):
            expenses=[{'label':e.get('name','Expenses'),'amount':rounded(e['amount'])} for e in entries]
    if not expenses and spending:expenses=[{'label':'Expenses','amount':rounded(spending)}]
    if abs(sum(num(e['amount']) for e in expenses)-spending)>Decimal('.02'):return None
    return dict(income=rounded(income),expenses=expenses,goal=rounded(contribution),left_over=rounded(income-spending-contribution),basis=basis)


def savings(inputs,actual,target,value,facts,reference):
    start=num(inputs['current_savings']);n=inputs.get('months',actual.get('months'))
    if target in ('months_to_goal','goal_deadline'):n=value
    if n is None or num(n)!=int(num(n)) or int(num(n))<0:return None
    n=int(num(n));goal=num(inputs['target']) if inputs.get('target') is not None else None
    c=num(value) if target in ('required_monthly_savings','monthly_contribution') else num(actual.get('monthly_savings',0 if n==0 else None))
    if start<0 or c<0:return None
    result={'kind':'one_time','options':[],'base_date':reference}
    if goal is not None:
        earned=c*n;draw=min(start,max(Decimal(0),goal-earned));short=max(Decimal(0),goal-earned-start)
        result['funding']=dict(goal=rounded(goal),from_income=rounded(min(earned,goal)),from_savings=rounded(draw),short=rounded(short))
        capacity=num(actual['monthly_surplus']) if actual.get('monthly_surplus') is not None else None
        def option(label,monthly,from_savings,months=n,current=False,plan_goal=goal):
            shortfall=max(Decimal(0),plan_goal-monthly*months-from_savings)
            if capacity is not None:shortfall=max(shortfall,(monthly-capacity)*months)
            return dict(label=label,current=current,feasible=shortfall<=Decimal('.01'),goal=rounded(plan_goal),months=months,budget_checked=capacity is not None,
                        monthly=rounded(monthly),from_savings=rounded(from_savings),savings_left=rounded(start-from_savings),short=rounded(shortfall))
        result['options'].append(option('Current plan',c,draw,current=True))
        if n:
            minimum=(max(Decimal(0),goal-start)/n).quantize(Decimal('.01'),rounding='ROUND_CEILING')
            if minimum<c:result['options'].append(option('Lower monthly saving, using available savings',minimum,min(start,max(Decimal(0),goal-minimum*n))))
            untouched=(goal/n).quantize(Decimal('.01'),rounding='ROUND_CEILING')
            if untouched!=c:
                opt=option('Keep existing savings untouched',untouched,Decimal(0))
                result['options'].append(opt)
            if short>0:
                if c>0:
                    later=math.ceil((goal-start)/c)
                    if later>n:result['options'].append(option(f'Delay the goal by {later-n} months',c,min(start,max(Decimal(0),goal-c*later)),months=later))
                lower=start+c*n
                if lower>0:result['options'].append(option(f'Lower the goal to {money(lower)}',c,start,plan_goal=lower))
        if start>=goal and n:result['options'].append(option('Pay from available savings now',Decimal(0),goal,months=0))
        if 0<n<=60:result['timeline']=[dict(month=i,set_aside=rounded(c*i)) for i in range(1,n+1)]
    elif 0<n<=60:
        result['timeline']=[dict(month=i,set_aside=rounded(start+c*i)) for i in range(1,n+1)]
    if inputs.get('monthly_income') is not None and actual.get('monthly_spending') is not None:
        result['budget']=budget(num(inputs['monthly_income']),num(actual['monthly_spending']),c,inputs.get('spending_entries'))
    return result


def recurring(inputs,actual,target,value):
    before=num(actual['monthly_surplus'])
    after=num(value) if target=='projected_surplus' else num(actual['scenario_monthly_surplus'])
    change=before-after
    if change<0:return None # income improvements need another chart, not a negative expense segment
    if inputs.get('monthly_surplus') is not None:
        now=budget(before,Decimal(0),Decimal(0),basis='surplus')
        then=budget(before,Decimal(0),change,basis='surplus')
    elif actual.get('monthly_income') is not None and actual.get('monthly_spending') is not None:
        income=num(actual['monthly_income']);spending=num(actual['monthly_spending'])
        now=budget(income,spending,Decimal(0),inputs.get('spending_entries'))
        then=budget(income,spending,change,inputs.get('spending_entries'))
    else:return None
    if now is None or then is None:return None
    return dict(kind='recurring',budget_now=now,budget_after=then,options=[
        dict(label='Without the new cost',current=False,feasible=before>=0,goal=0,left_each_month=rounded(before)),
        dict(label='With the new cost',current=True,feasible=after>=0,goal=rounded(change),left_each_month=rounded(after),short=rounded(max(Decimal(0),-after)))])


def narrative(response,visuals,inputs,actual):
    """Grace's explanation + suggested user messages, grounded in the chosen plan."""
    model=response.get('model');target=response.get('target_variable');matched=response.get('verification',{}).get('status')=='matched'
    if matched and visuals and visuals['kind']=='one_time':
        c=num(actual.get('required_monthly_savings',actual.get('monthly_savings',0)));n=inputs.get('months',actual.get('months'))
        start=num(inputs['current_savings']);goal=inputs.get('target')
        if int(n)==0:
            text=f"For a purchase today, you have {money(start)} toward the {money(goal)} price." if goal is not None else f"You have {money(start)} available today."
            if visuals.get('funding') and num(visuals['funding']['short'])>0:text+=f" You need {money(visuals['funding']['short'])} more."
        elif goal is None:
            text=f"Adding {money(c)} a month for {n} months brings your balance to {money(start+c*int(n))}."
        else:
            text=f"Saving {money(c)} a month for {n} months adds {money(c*int(n))}."
            f=visuals.get('funding',{});draw=num(f.get('from_savings',0));short=num(f.get('short',0))
            if short>0:text+=f" Even using your available savings, you would be {money(short)} short."
            elif draw>0:text+=f" You would use {money(draw)} from savings to cover the rest."
            else:text=f'At {money(c)} a month, you can save {money(c*int(n))} in {n} months without using your existing savings.'
        suggestions=([f'What if the price is {money(start)} instead?', 'What if I buy it later?'] if int(n)==0 else [f'What if I have {int(n)+1} months instead?',f'What if I save {money(max(Decimal(1),c*Decimal(".8")))} each month?'])
    elif matched and visuals and visuals['kind']=='recurring':
        b=visuals['budget_now'];a=visuals['budget_after'];change=num(a['goal'])
        text=f"The additional {money(change)} monthly cost takes your monthly cushion from {money(b['left_over'])} to {money(a['left_over'])}."
        if a['left_over']<0:text+=' That would create a monthly shortfall.'
        full=num(inputs.get('spending_change',change))
        suggestions=[f'What if the new recurring cost is {money(full*Decimal(".9"))} per month?',f'What if I have {money(num(b["left_over"])+100)} left each month before the new cost?']
    else:
        detail=response.get('answer',{}).get('headline','')
        text=detail
        if response.get('verification',{}).get('status')=='mismatch':text+=' The independent check differs, so review the warning before relying on this result.'
        elif not matched:text+=' The independent check could not verify this result.'
        suggestions={'savings_goal':['What if I have one more month?','What if I save less each month?'],
                     'bill_split':['What if we split it equally instead?','What if the tip changes?'],
                     'debt_repayment':['What if I increase my monthly payment?','What if I pay it off sooner?']}.get(model,[])
    return {'text':text,'suggestions':suggestions}


def attach(response,draft,selection,req,facts,actual):
    """Best-effort only; never mutate the core response or require chart inputs."""
    if response.get('status') not in ('ready','conditional'):return response
    result=copy.deepcopy(response);visuals=None
    actual=copy.deepcopy(actual) if actual else actual
    if actual and actual.get('monthly_spending') is None and actual.get('monthly_savings') is not None:
        native=(selection or {}).get('input_plan',{}).get('inputs',{})
        if native.get('monthly_income') is not None and native.get('spending_entries'):
            actual['monthly_spending']=str(num(native['monthly_income'])-num(actual['monthly_savings']))
    inputs=(selection or {}).get('input_plan',{}).get('inputs') or draft.get('inputs',{})
    try:
        if response.get('verification',{}).get('status')=='matched' and actual:
            if response.get('model')=='savings_goal':
                visuals=savings(inputs,actual,response['target_variable'],response['verification']['main_value'],facts,
                                req.get('extraction_meta',{}).get('selection_state',{}).get('reference_date'))
            elif response.get('model')=='budget_cash_flow':visuals=recurring(inputs,actual,response['target_variable'],response['verification']['main_value'])
    except (ValueError,TypeError,KeyError,ArithmeticError):visuals=None
    if visuals:result['visuals']=visuals
    result['narrative']=narrative(response,visuals,inputs,actual or {})
    calendar_note=next((a.get('source_detail') for a in facts.values() if a.get('source_detail','').startswith('Calendar assumption:')),None)
    if calendar_note:
        import calendar_horizon
        result['narrative']['text']+=' '+calendar_horizon.short_note(calendar_note)
        result.setdefault('assumptions',[]).append({'id':'calendar-timing','text':calendar_note})
    proposed=draft.get('narrative')
    # A chart's narrative is assembled from its exact current-plan fields. A
    # free-form draft can otherwise relabel a known amount (e.g. call the $300
    # remainder the rent increase), despite passing a numeric allowlist.
    if not visuals and response.get('verification',{}).get('status')=='matched' and isinstance(proposed,dict):
        try:
            from answer_verification import same_final
            unit=response['verification'].get('unit','text')
            if unit=='text':
                canonical=lambda v:{'true':'yes','false':'no'}.get(str(v).lower(),str(v).lower())
                differs=canonical(proposed.get('primary_value'))!=canonical(response['verification']['main_value'])
            else:differs=bool(same_final(proposed.get('primary_value'),response['verification']['main_value'],unit,'answer'))
            if differs:raise ValueError('Narrative target differs')
            if not isinstance(proposed.get('text'),str):raise ValueError('Invalid narrative text')
            text=proposed['text'].strip()
            if not text or len(text)>360 or len(text.split())>55 or '|' in text:raise ValueError('Not concise narrative')
            amounts=[]
            def collect(value):
                if isinstance(value,bool):return
                if isinstance(value,(float,int,Decimal)):amounts.append(abs(num(value)))
                elif isinstance(value,dict):
                    for v in value.values():collect(v)
                elif isinstance(value,list):
                    for v in value:collect(v)
            # An alternative plan's amounts must not silently become the
            # explanation of the displayed current plan.
            collect({k:v for k,v in (visuals or {}).items() if k!='options'})
            collect(response['verification']['main_value'])
            for fact in facts.values():
                if str(fact.get('unit') or '').startswith('$'):
                    try:amounts.append(abs(num(fact['value'])))
                    except (ValueError,TypeError,ArithmeticError):pass
            for value in re.findall(r'\$\s*([\d,]+(?:\.\d+)?)',text):
                if not any(abs(num(value.replace(',',''))-n)<=Decimal('.01') for n in amounts):raise ValueError('Unsupported narrative amount')
            raw_suggestions=proposed.get('suggestions',[])
            suggestions=[s.strip() for s in raw_suggestions if isinstance(s,str) and 0<len(s.strip())<=100][:3] if isinstance(raw_suggestions,list) else []
            suggestions=[re.sub(r'\byour\b','my',re.sub(r'\byou\b','I',s,flags=re.I),flags=re.I) for s in suggestions]
            result['narrative']={'text':text,'suggestions':suggestions}
        except (ValueError,TypeError,KeyError,ArithmeticError):pass
    return result


def attach_scoped(response,req):
    """Support a complete deposit schedule without registering a new solver.

    Main remains the answer source. Display a schedule only if its endpoint agrees
    with Main; the existing unavailable-verifier warning remains unchanged.
    """
    import json
    result=copy.deepcopy(response)
    if result.get('status') not in ('ready','conditional'):return result
    result['narrative']={'text':'The calculation uses the amounts and timing you supplied.', 'suggestions':[]}
    facts={a['variable']:a.get('value') for a in req.get('assumptions',[]) if a.get('value') is not None}
    for f in result.get('factors',[]):
        if f.get('role')=='known':facts.setdefault(f['variable'],f.get('value'))
    try:
        entries=facts.get('contribution_entries')
        if isinstance(entries,str):entries=json.loads(entries)
        if not isinstance(entries,list) or len(entries)!=1:return result
        e=entries[0];count=int(e['count']);amount=num(e['amount'])
        if count!=num(e['count']) or not 0<count<=60 or amount<0:return result
        frequency=e['frequency']
        if frequency not in ('weekly','monthly','daily'):return result
        start=num(facts.get('current_savings',facts.get('available_savings')))
        final=num(result['verification']['main_value'])
        if abs(start+amount*count-final)>Decimal('.005'):return result
        period={'weekly':'week','monthly':'month','daily':'day'}[frequency]
        result['visuals']={'kind':'deposits','period':period,'start':rounded(start),'amount':rounded(amount),
                           'timeline':[{'deposit':i,'balance':rounded(start+amount*i)} for i in range(1,count+1)]}
        result['narrative']={'text':f'Your {count} deposits of {money(amount)}, one each {period}, add {money(amount*count)} to your starting {money(start)}.',
                             'suggestions':[f'What if I make {count+1} deposits instead?',f'What if I deposit {money(amount+10)} each {period}?']}
    except (ValueError,TypeError,KeyError,ArithmeticError):pass
    return result
