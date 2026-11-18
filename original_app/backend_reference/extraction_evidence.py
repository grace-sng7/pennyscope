"""Ground extracted literals in user/profile/state evidence; never do arithmetic."""
import json
import re
import base_input_rules
from decimal import Decimal
from pydantic import BaseModel, ConfigDict
from typing import Literal


class Evidence(BaseModel):
    model_config=ConfigDict(extra='forbid')
    source: Literal['question','correction','history','profile','previous']
    quote: str | None = None
    variable: str | None = None


_WORDS=dict(zip(('zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve','thirteen','fourteen','fifteen','sixteen','seventeen','eighteen','nineteen','twenty'),range(21)))
_NUMBERS=re.compile(r'(?<![\w.])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\w|\.\d)')


def numbers(text):
    result={Decimal(m.group().replace(',','')) for m in _NUMBERS.finditer(text)}
    result.update(Decimal(_WORDS[w.lower()]) for w in re.findall(r'\b\w+\b',text) if w.lower() in _WORDS)
    return result


def decoded(value):
    if isinstance(value,str):
        try:return json.loads(value)
        except ValueError:pass
    return value


def numeric_leaves(value):
    value=decoded(value)
    if isinstance(value,bool):return []
    if isinstance(value,(int,float,Decimal)):return [Decimal(str(value))]
    if isinstance(value,dict):return [n for v in value.values() for n in numeric_leaves(v)]
    if isinstance(value,list):return [n for v in value for n in numeric_leaves(v)]
    if isinstance(value,str):return list(numbers(value))
    return []


def _category_supported(name,kind,text):
    subject=r'(?:income|pay|earnings|salary)' if kind=='income' else r'(?:costs|expenses|spending|bills)'
    return bool(re.search(r'\b'+name+r'\s+(?:monthly\s+)?'+subject+r'\b|\b'+subject+r'\s+(?:is|are)\s+(?:explicitly\s+)?'+name+r'\b',text,re.I))


def _categories(factor,text):
    kind='income' if factor.variable in ('fixed_income','variable_income','income_entries') else 'spending'
    category={'fixed_income':'fixed','variable_income':'variable','fixed_costs':'fixed','variable_costs':'variable'}.get(factor.variable)
    if category and not _category_supported(category,kind,text):raise ValueError('Category is not explicitly supplied')
    if factor.variable in ('income_entries','spending_entries'):
        for entry in decoded(factor.value):
            category=entry.get('category')
            if category is not None and not _category_supported(category,kind,text):raise ValueError('Entry category is not explicitly supplied')


def _same(a,b):
    return decoded(a)==decoded(b)


def _contribution_supported(value,text,surplus=False):
    """The same literal in an earnings clause is not a savings commitment."""
    relation=r'\b(?:surplus|left(?: over)?|remain\w*)\b|\bafter\b.{0,35}\bexpenses\b'
    if not surplus:
        relation+=r'|\b(?:save|saves|saving|contribut\w*|deposit\w*|spare)\b|\bset(?:ting)?\b.{0,35}\baside\b|\bput(?:ting)?\b.{0,40}\b(?:aside|towards?)\b|\bsaved\b.{0,35}\bmonth'
    for clause in re.split(r'\b(?:and|but)\b|[;!?]|\.(?!\d)',text.replace('’',"'"),flags=re.I):
        if re.search(r"\b(?:can't|cannot|don't|do not|won't|never|not sure|unsure)\b",clause,re.I):continue
        if all(n in numbers(clause) for n in numeric_leaves(value)) and re.search(relation,clause,re.I):return True
    return False


def _person(name):
    text=str(name).strip().lower().replace('’', "'")
    return 'me' if text in ('i','me','my','myself','user','the user','speaker','you') else text


def _bill_people(text, selected_factors, previous):
    names=[]
    for factor in list(selected_factors or [])+list(previous or []):
        name=factor.variable if hasattr(factor,'variable') else factor.get('variable')
        value=factor.value if hasattr(factor,'value') else factor.get('value')
        if name in ('participants','people') and isinstance(decoded(value),list):names.extend(decoded(value))
    if not names:
        # Names are entities, not a whitelist of itemized-split phrases.
        ignored={'the','tax','tip','we','there','how','what','dinner','my','each','before','after','a'}
        names=[word for word in re.findall(r'\b[A-Z][a-z]+\b',text) if word.lower() not in ignored]
        if re.search(r'\b(?:I|me|my|us|we)\b',text,re.I):names.append('me')
    return list(dict.fromkeys(_person(name) for name in names))


def _people_in(text,people):
    found={name for name in people if name!='me' and re.search(r'\b'+re.escape(name)+r"(?:'s)?\b",text,re.I)}
    if 'me' in people and re.search(r'\b(?:I|me|my|myself|the user|speaker)\b',text,re.I):found.add('me')
    return found


def _ownership(clause,people):
    clause=clause.replace('’',"'")
    # Relations bind an item to its consumers. Negated sharing is not a second
    # owner, and merely ordering different things is not an allocation rule.
    shared=re.search(r'\b(?:shared?|split|divided?)\b',clause,re.I)
    if shared and not re.search(r"\b(?:not|never|didn't|wasn't|weren't)\b",clause[:shared.start()],re.I) and not re.search(r'\b(?:proportion|proportional|tax|tip)\b',clause,re.I):
        owners=_people_in(clause,people)
        if not owners and re.search(r'\b(?:we|us|everyone|all)\b',clause,re.I):owners=set(people)
        if owners:return owners
    active=re.search(r'\b(?:had|ordered|ate|got|chose|bought|took|consumed)\b',clause,re.I)
    if active:
        if re.search(r"\b(?:not|never|didn't)\s*$",clause[:active.start()],re.I):return set()
        owners=_people_in(clause[:active.start()],people)
        if owners:return owners
    possessive=re.search(r"\b(?:was|is|were|are|belongs? to|for)\s+(.+)",clause,re.I)
    if possessive:
        owners=_people_in(possessive.group(1),people)
        if owners:return owners
    owners={name for name in people if name!='me' and re.search(r'\b'+re.escape(name)+r"'s\s+\w",clause,re.I)}
    if 'me' in people and re.search(r'\bmy\s+\w',clause,re.I):owners.add('me')
    return owners


def _bill_clauses(text,people):
    text=text.replace('’',"'")
    subjects='|'.join(re.escape(name) for name in people if name!='me')
    subjects=(subjects+'|' if subjects else '')+r'I|me'
    text=re.sub(r',?\s+and\s+(?=(?:'+subjects+r')\s+(?:also\s+)?(?:had|ordered|ate|got|chose|bought|took)\b)', '\n',text,flags=re.I)
    return [part.strip() for part in re.split(r'[!?;\n]|\.(?!\d)',text) if part.strip()]


def _item_claims(items,text,people):
    if not isinstance(items,list) or not items:return False
    clauses=_bill_clauses(text,people)
    money=re.compile(r'\$\s*(\d[\d,]*(?:\.\d+)?)|\b(\d[\d,]*(?:\.\d+)?)\s+dollars?\b',re.I)
    used=set()
    for item in items:
        if not isinstance(item,dict) or not isinstance(item.get('shared_by'),list) or not item['shared_by']:return False
        owners={_person(name) for name in item['shared_by']}
        if len(owners)!=len(item['shared_by']) or not owners<=set(people):return False
        try:amount=Decimal(str(item['amount']))
        except Exception:return False
        label=str(item.get('name') or item.get('item') or item.get('description') or '').lower()
        label=re.sub(r"\b(?:"+'|'.join(re.escape(p) for p in people if p!='me')+r")'s\b",'',label) if any(p!='me' for p in people) else label
        tokens=[token for token in re.findall(r'[a-z]+',label) if token not in ('a','an','the','shared','my','me')]
        matched=False
        for index,clause in enumerate(clauses):
            prices=list(money.finditer(clause))
            for price_index,price in enumerate(prices):
                if (index,price_index) in used or Decimal((price.group(1) or price.group(2)).replace(',',''))!=amount:continue
                if tokens:
                    positions=[match for token in tokens for match in re.finditer(r'\b'+re.escape(token)+r'\b',clause,re.I)]
                    if not positions or not any(min(range(len(prices)),key=lambda i:abs(prices[i].start()-position.start()))==price_index for position in positions):continue
                supported=_ownership(clause,people)
                if supported!=owners and tokens:
                    # Link a price to a separately stated possessive by item
                    # identity, e.g. "$10 salad. The salad was Nina's."
                    relations=[_ownership(other,people) for other in clauses if not money.search(other) and all(re.search(r'\b'+re.escape(token)+r'\b',other,re.I) for token in tokens)]
                    supported=relations[0] if len(relations)==1 else supported
                if supported==owners:
                    used.add((index,price_index));matched=True;break
            if matched:break
        if not matched:return False
    return True


def _itemized_supported(text, selected_factors, previous):
    people=_bill_people(text,selected_factors,previous)
    items=[]
    for f in selected_factors or []:
        if f.variable in ('items','shared_items') and f.value is not None:items.extend(decoded(f.value))
    if items:return _item_claims(items,text,people)
    if re.search(r'\bitemi[sz]ed\b|\bby what\b|\baccording to (?:the )?items\b',text,re.I):return True
    return any(_ownership(clause,people) for clause in _bill_clauses(text,people) if re.search(r"\b(?:had|ordered|ate|got|chose|bought|took|belongs? to)\b|\b(?:was|is)\s+\w+'s\b",clause,re.I))

def validate(factor, registry, *, question, correction, history, profile, previous, selected_factors=None):
    """Return verified evidence; inferred/approximate facts need grounding too."""
    if factor.value is None:return None
    aliases=registry.aliases or {}
    canonical=lambda name:aliases.get(name,name)
    def existing(source,name):
        if source=='profile':
            for key,value in profile.items():
                if canonical(key)==canonical(name) and _same(value,factor.value):return key
        else:
            for item in previous:
                if item['role']=='known' and canonical(item['variable'])==canonical(name) and _same(item['value'],factor.value) and item.get('unit')==factor.unit:return item['variable']
        return None
    text_sources={'question':[question], 'correction':[correction] if correction is not None else [],
                  'history':[m.get('content','') for m in history if m.get('role')=='user' and isinstance(m.get('content'),str)]}
    evidence=factor.evidence
    if evidence and evidence.source in ('profile','previous'):
        if not evidence.variable or canonical(evidence.variable)!=canonical(factor.variable):raise ValueError('Evidence factor differs')
        key=existing(evidence.source,evidence.variable)
        if key is None:raise ValueError('No matching stored fact')
        return Evidence(source=evidence.source,variable=key)
    if not evidence:
        for source in ('profile','previous'):
            key=existing(source,factor.variable)
            if key is not None:return Evidence(source=source,variable=key)
    candidates=[]
    if evidence:
        if not evidence.quote or not any(evidence.quote in text for text in text_sources[evidence.source]):raise ValueError('Evidence quote is not verbatim')
        candidates=[(evidence.source,text) for text in text_sources[evidence.source] if evidence.quote in text] if registry.model=='bill_split' and factor.variable in ('items','shared_items','split_method','method') else [(evidence.source,evidence.quote)]
    else:
        candidates=[(source,text) for source,texts in text_sources.items() for text in texts]
    required=numeric_leaves(factor.value)
    for source,text in candidates:
        supplied=numbers(text)
        contextual=False
        if Decimal(0) in required and base_input_rules.contextual_zero(factor.variable,text):
            supplied.add(Decimal(0));contextual=True
        if factor.variable in ('participants','people') and len(required)==1 and base_input_rules.named_count(text)==required[0]:
            supplied.add(required[0]);contextual=True
        if not all(n in supplied for n in required):continue
        all_user='\n'.join(text_sources['question']+text_sources['correction']+text_sources['history'])
        if registry.model in ('savings_goal','budget_cash_flow') and factor.variable in ('monthly_contribution','monthly_savings','monthly_surplus'):
            if not _contribution_supported(factor.value,text,surplus=factor.variable=='monthly_surplus'):continue
        if factor.variable in ('participants','people') and isinstance(decoded(factor.value),list):
            names=decoded(factor.value)
            if not all((_person(name)=='me' and re.search(r'\b(?:I|me|my|us|we)\b',all_user,re.I)) or (_person(name)!='me' and re.search(r'\b'+re.escape(str(name))+r'\b',all_user,re.I)) for name in names):continue
        if factor.variable in ('items','shared_items'):
            if not _item_claims(decoded(factor.value),text,_bill_people(all_user,selected_factors,previous)):continue
        if factor.variable in ('split_method','method') and decoded(factor.value)=='itemized':
            if not _itemized_supported(all_user,selected_factors,previous):continue
            if not re.search(r'itemi[sz]ed',all_user,re.I):contextual=True
        if contextual:
            factor.source='inferred'
            if hasattr(factor,'inference'):factor.inference='Contextual input interpretation supported by the quoted user facts.'
        try:_categories(factor,text)
        except ValueError:continue
        # Text literals need an explicit supported label or verbatim occurrence.
        if not required and isinstance(decoded(factor.value),str):
            value=str(factor.value)
            if factor.variable not in ('goal_description','split_method','method') and value.lower() not in text.lower():continue
        return Evidence(source=source,quote=text)
    raise ValueError('Extracted value is not supported by evidence')
