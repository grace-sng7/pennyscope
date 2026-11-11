"""Conservative fast path for ordinary updates; all intent interpretation is Router's."""
import re


def ordinary_update(message, registry):
    text=message.strip()
    if re.search(r'\b(?:new|different|another)\s+(?:financial\s+)?(?:question|topic|goal)\b|\b(?:split|reimburse|who owes|instead|switch)\b|\?',text,re.I):return False
    if re.fullmatch(r'\$?[+-]?[\d,]+(?:\.\d+)?\s*(?:%|months?|per month|/month)?[.!]?',text,re.I):return True
    stripped=re.sub(r'\s*everything else (?:stays|is|remains) (?:the )?same[.!]?\s*$','',text,flags=re.I).strip()
    if registry.model in ('budget_cash_flow','savings_goal') and re.fullmatch(
        r'(?:actually[, ]*)?I (?:spend|earn|make) \$?[\d,]+(?:\.\d+)?\s*(?:monthly|per month|/month)[.!]?',stripped,re.I):
        return True
    # An explicit factor assignment is a continuation, not a model-selection task.
    names=[re.escape(k).replace('_',r'[_ ]') for k in registry.factors]
    names+=['goal','goal amount','monthly spending','monthly income','deadline','APR','payment']
    label='(?:'+'|'.join(names)+')'
    return bool(re.fullmatch(r'(?:actually[, ]*|correction[: ,]*|update[: ,]*)?(?:the |my )?'+label+r'\s*(?::|=|is actually|is now|is|was|should be|costs)\s*\$?[+-]?[\d,]+(?:\.\d+)?\s*(?:%|months?|per month|/month)?[.!]?',stripped,re.I))
