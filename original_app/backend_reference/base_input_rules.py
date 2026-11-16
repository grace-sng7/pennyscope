"""Shared input interpretation, not a financial model or answer generator.

Keep literal quantities separate from contextual inferences. Never manufacture
financial totals, future contributions, APR or sharing agreements.
"""
import copy
import json
import re
from decimal import Decimal

ARRAYS={'income_entries','spending_entries','spending_change_entries','expense_categories','expense_adjustments','items','shared_items','settlements','contribution_entries'}
OBJECTS={'split_weights','weights','amounts_paid','amounts_owed'}
MONTHLY={'monthly_income','monthly_expenses','monthly_spending','monthly_surplus','monthly_contribution','monthly_savings','required_monthly_savings','projected_surplus','monthly_payment','required_monthly_payment','fixed_income','variable_income','fixed_costs','variable_costs','spending_change','income_change','replaced_recurring_cost'}
MONTHLY_TEXT=re.compile(r'\bmonth(?:ly)?\b|/month',re.I)
OTHER_PERIOD=re.compile(r'\bweek(?:ly)?\b|biweekly|semimonthly|quarter(?:ly)?|annual(?:ly)?|year(?:ly)?',re.I)


def normalize(raw,registry,question,correction=None,history=()):
    raw=copy.deepcopy(raw)
    if not isinstance(raw,dict):return raw
    text='\n'.join([question,correction or '',*[m.get('content','') for m in history if m.get('role')=='user']])
    monthly_context=bool(MONTHLY_TEXT.search(text)) and not OTHER_PERIOD.search(text)
    for factor in raw.get('factors',[]):
        if not isinstance(factor,dict):continue
        name=factor.get('variable');value=factor.get('value')
        # Correct a source locator only when its quote is verbatim in an actual
        # user message. Never change the quote or relax numeric grounding.
        evidence=factor.get('evidence')
        if isinstance(evidence,dict) and evidence.get('quote'):
            quote=evidence['quote']
            texts={'question':[question],'correction':[correction] if correction else [],'history':[m.get('content','') for m in history if m.get('role')=='user']}
            if evidence.get('source') in texts and not any(quote in t for t in texts[evidence['source']]):
                for source in ('correction','question','history'):
                    if any(quote in t for t in texts[source]):evidence['source']=source;break
        if name in ARRAYS|OBJECTS and isinstance(value,(list,dict)):
            factor['value']=json.dumps(value)
        if name in ('participants','people') and isinstance(value,list):factor['value']=json.dumps(value)
        if factor.get('unit') in ('count','people','persons','participants','boolean') or factor.get('variable')=='affordability_status':factor['unit']='text'
        if name in ARRAYS|OBJECTS and factor.get('value') is not None:factor['unit']='text'
        if name in MONTHLY and factor.get('unit') in (None,'$') and monthly_context:
            factor['unit']='$/month'
        if name=='recurring_cost' and factor.get('unit') in (None,'$') and monthly_context:
            factor['unit']='$/month'
            factor['source']='inferred'
            factor['source_detail']='Monthly billing inferred from the ongoing monthly replacement context; amount is supplied.'
            factor['inference']='Monthly frequency follows the current monthly charge being replaced.'
    if registry.model=='savings_goal':
        # A count of monthly deposits is already in the calculator's period;
        # retain its literals rather than converting or rejecting the schedule.
        schedule=next((f for f in raw.get('factors',[]) if f.get('variable')=='contribution_entries' and f.get('value') is not None),None)
        if schedule:
            try:entries=json.loads(schedule['value']) if isinstance(schedule['value'],str) else schedule['value']
            except (ValueError,TypeError):entries=None
            evidence=schedule.get('evidence')
            quote=(evidence or {}).get('quote') or text
            if isinstance(entries,list) and len(entries)==1 and isinstance(entries[0],dict) and entries[0].get('frequency')=='monthly' and MONTHLY_TEXT.search(quote) and not OTHER_PERIOD.search(quote):
                entry=entries[0]
                supplied={f.get('variable') for f in raw['factors'] if f.get('value') is not None}
                for name,key,unit in [('monthly_contribution','amount','$/month'),('contribution_months','count','months')]:
                    value=entry.get(key)
                    if name in supplied or isinstance(value,bool) or not isinstance(value,(int,float)):continue
                    if key=='count' and (value<0 or int(value)!=value):continue
                    raw['factors']=[f for f in raw['factors'] if f.get('variable')!=name]
                    raw['factors'].append(dict(variable=name,value=value,unit=unit,role='known',source='inferred',source_detail='Literal value from the supplied monthly deposit schedule.',relevant=True,evidence=copy.deepcopy(evidence) if evidence and evidence.get('source') not in ('previous','profile') else None,inference='The deposit frequency is monthly; its literal count is the contribution horizon.'))
    if registry.model=='savings_goal' and contextual_zero('goal_deadline',question):
        deadline=next((f for f in raw.get('factors',[]) if f.get('variable') in ('goal_deadline','months')),None)
        if deadline is None:
            raw.setdefault('factors',[]).append(dict(variable='goal_deadline',value=0,unit='months',role='known',source='inferred',source_detail='Today means no future contributions.',relevant=True,evidence={'source':'question','quote':question}))
    return raw


def contextual_zero(name,text):
    if name in ('tax_amount','tax'):
        return bool(re.search(r'\b(?:no|without)\s+(?:any\s+)?tax\b',text,re.I))
    if name in ('tip_amount','tip'):
        return bool(re.search(r'\b(?:no|without)\s+(?:any\s+)?(?:tax\s*(?:or|and|/)\s*)?tip\b',text,re.I))
    if name in ('goal_deadline','months'):
        return bool(re.search(r'\b(?:today|right now|immediately)\b',text,re.I))
    return False


def named_count(text):
    parts=re.split(r'\s*(?:,\s*(?:and\s+)?|\band\b|&)\s*',text.strip())
    return len(parts) if len(parts)>1 and all(re.fullmatch(r'(?:[A-Z][a-z]+(?: [A-Z][a-z]+)*|I|me|the user)',p) for p in parts) else None


def clarification_context(previous,question,reference_date,timezone):
    """Reconstruct the question this backend asks from its own validated state.

    This lets a bare reply bind to the required variable without any exemplar or
    test-provided answer key entering the conversation.
    """
    import calculation_handoff
    assumptions=previous.get('assumptions',[])
    facts={a['variable']:a for a in assumptions}
    request={'original_question':question,'assumptions':assumptions,'extraction_meta':previous}
    _,response=calculation_handoff.resolve(request,facts)
    if response and response.get('status')=='needs_input' and len(response.get('missing_inputs',[]))==1:
        item=response['missing_inputs'][0]
        return {'role':'assistant','content':json.dumps({'required_input':item['variable'],'question':item['label']})}
    return None


def bind_required_reply(previous,question,reply,reference_date,timezone):
    context=clarification_context(previous,question,reference_date,timezone)
    if context is None:return previous,False
    pending=json.loads(context['content'])
    name=pending['required_input']
    match=re.fullmatch(r'\s*\$?([+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)\s*%?\s*',reply)
    if not match or name in ('model_selection','target_selection','split_method'):return previous,False
    value=Decimal(match.group(1).replace(',',''));value=int(value) if value==int(value) else float(value)
    unit='$/month' if name in MONTHLY else '%' if name=='apr' else 'months' if name in ('goal_deadline','contribution_months','payoff_months') else '$'
    fact=dict(variable=name,value=value,unit=unit,source='stated',source_detail='User reply to required question: '+pending['question'],edited_by_user=True)
    updated=copy.deepcopy(previous)
    assumptions={a['variable']:a for a in updated.get('assumptions',[])};assumptions[name]=fact
    updated['assumptions']=list(assumptions.values())
    factors={f['variable']:f for f in updated.get('factors',[])};factors[name]={**fact,'role':'known','relevant':True}
    updated['factors']=list(factors.values())
    return updated,True


def complete_spending_evidence(text):
    # A question about "all expenses" does not assert that a listed item is all
    # spending. Require a statement describing the coverage of the amounts.
    return bool(re.search(r'everything else|(?:all|total|complete|entire|usual)\s+(?:monthly\s+)?(?:spending|expenses|bills|costs)\s*(?:are|is|total|=|:|come|add)|(?:spending|expenses|bills|costs)\s+(?:are|is|total|comes|add|=|:)',text,re.I))


def normalize_draft(draft):
    draft=copy.deepcopy(draft)
    for factor in draft.get('factors',[]):
        if isinstance(factor.get('value'),(list,dict)):factor['value']=json.dumps(factor['value'])
        if factor.get('unit') in ('count','people','persons','participants','boolean') or factor.get('variable')=='affordability_status':factor['unit']='text'
    return draft
