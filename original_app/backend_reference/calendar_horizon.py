"""Deterministic calendar assumptions, separate from LLM literal extraction."""
import calendar
import copy
from datetime import date
import re

PREFIX='Calendar assumption:'
MONTHS={name.lower():i for i,name in enumerate(calendar.month_name) if name}
MONTHS.update({name.lower():i for i,name in enumerate(calendar.month_abbr) if name})


def infer(deadline,reference):
    try:today=date.fromisoformat(reference)
    except (TypeError,ValueError):return None
    if not isinstance(deadline,str):return None
    text=deadline.strip().lower().rstrip('.')
    month_only=False
    try:due=date.fromisoformat(text)
    except ValueError:
        match=re.fullmatch(r'(?:(?:by|in|before)\s+)?(?:(next|this)\s+)?([a-z]+)(?:\s+(\d{4}))?',text)
        if not match or match[2] not in MONTHS:return None
        modifier,word,year=match.groups();month=MONTHS[word]
        year=int(year) if year else today.year+(month<=today.month and modifier!='this')
        try:due=date(year,month,calendar.monthrange(year,month)[1])
        except ValueError:return None
        month_only=True
    if due<today:return None
    count=(due.year-today.year)*12+due.month-today.month
    if not month_only and due.day<min(today.day,calendar.monthrange(due.year,due.month)[1]):count-=1
    if count<0:return None
    note=f'{PREFIX} using {today.isoformat()} as the reference date'
    if month_only:note+=f' and the end of {due.strftime("%B %Y")} as the deadline'
    else:note+=f' and {due.isoformat()} as the deadline'
    note+=f', allow {count} monthly saving periods. No extra deposit is assumed for the current partial month. Correct the deadline or timing if needed.'
    return dict(variable='contribution_months',value=count,unit='months',role='derived',source='inferred',source_detail=note,relevant=True)


def short_note(note):
    month=re.search(r'and the end of ([A-Za-z]+ \d{4}) as the deadline',note)
    if month:return 'Assumes the end of '+month[1]+'.'
    exact=re.search(r'and (\d{4}-\d{2}-\d{2}) as the deadline',note)
    if exact:
        due=date.fromisoformat(exact[1])
        return f'Assumes a {due.strftime("%B")} {due.day}, {due.year} deadline.'
    return ''


def annotate(response):
    if response.get('model')!='savings_goal' or response.get('target_variable') in ('months_to_goal','goal_deadline'):return response
    result=copy.deepcopy(response)
    assumptions=result.get('assumptions',[])
    explicit=next((a for a in assumptions if a['variable']=='contribution_months' and a.get('value') is not None and not a.get('source_detail','').startswith(PREFIX)),None)
    if explicit:return response
    deadline=next((a for a in assumptions if a['variable']=='goal_deadline' and a.get('value') is not None),None)
    if not deadline or not isinstance(deadline['value'],str):return response
    fact=infer(deadline['value'],result.get('selection_state',{}).get('reference_date'))
    result['assumptions']=[a for a in assumptions if not (a['variable']=='contribution_months' and a.get('source_detail','').startswith(PREFIX))]
    result['factors']=[f for f in result.get('factors',[]) if not (f['variable']=='contribution_months' and f.get('source_detail','').startswith(PREFIX))]
    if fact:
        result['assumptions']=[a for a in result['assumptions'] if a['variable']!='contribution_months']+[ {k:fact[k] for k in ('variable','value','unit','source','source_detail')} ]
        result['factors']=[f for f in result['factors'] if f['variable']!='contribution_months']+[fact]
        result['confidence_note']=(result.get('confidence_note','').split(PREFIX)[0]+' '+fact['source_detail']).strip()
        result['assistant_message']=result.get('goal_summary','Here is what I understood.')+' '+short_note(fact['source_detail'])
    return result
