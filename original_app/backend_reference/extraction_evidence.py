"""Ground extracted literals in user/profile/state evidence; never do arithmetic."""
import json
import re
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


def validate(factor, registry, *, question, correction, history, profile, previous):
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
        candidates=[(evidence.source,evidence.quote)]
    else:
        candidates=[(source,text) for source,texts in text_sources.items() for text in texts]
    required=numeric_leaves(factor.value)
    for source,text in candidates:
        if not all(n in numbers(text) for n in required):continue
        try:_categories(factor,text)
        except ValueError:continue
        # Text literals need an explicit supported label or verbatim occurrence.
        if not required and isinstance(decoded(factor.value),str):
            value=str(factor.value)
            if factor.variable not in ('goal_description','split_method','method') and value.lower() not in text.lower():continue
        return Evidence(source=source,quote=text)
    raise ValueError('Extracted value is not supported by evidence')
