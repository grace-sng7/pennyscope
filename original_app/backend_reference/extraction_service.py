"""Explicit routing -> Python registry lookup -> factor extraction.

No calculator, missing-input checker, primary-answer prompt or Inspector runs
here. Existing downstream endpoints retain their own responsibilities.
"""
from fastapi import HTTPException
import hashlib
import json
import time
import threading
from collections import OrderedDict
import model_router
import factor_selection
import intent_transition
from factor_registry import get_registry
from contract import ExtractionResponse


PENDING_ROUTES=OrderedDict()
_ROUTE_LOCK=threading.RLock()
_ROUTE_TTL=1800
_ROUTE_LIMIT=128

def _unresolved(decision, question, revision=0):
    if decision.model=='ambiguous':
        message=decision.clarification
    elif decision.model=='multiple':
        names=', '.join(m.replace('_',' ') for m in decision.models)
        message=f'Your question involves {names}. Which part would you like to address first?'
    else:message='I’ll work through this question using the information you provided.'
    return {'model':None,'target_variable':None,'factors':[], 'assumptions':[],
            'clarification_questions':[] if decision.model=='gap' else [{'target_variable':'model_selection','question':message,'why_it_matters':'Select a financial intent before extracting model-specific factors.'}],
            'goal_summary':message,'confidence_note':'No model-specific factor extraction has run.',
            'routing':decision.model_dump(exclude_defaults=True),
            'selection_state':{'model':None,'revision':revision,'history':[{'role':'user','content':question}]}}


def _extract_branch(decision, question, reference_date, timezone, *, history=None, profile=None, previous=None, correction=None):
    revision=(previous or {}).get('selection_state',{}).get('revision',-1)+1
    if decision.model in ('gap','ambiguous','multiple'):
        response=_unresolved(decision,question,revision)
        response['selection_state']['history']=[*(history or []),{'role':'user','content':correction if correction is not None else question}][-12:]
        return response
    # This lookup is the only transition from a validated route to a branch.
    registry=get_registry(decision.model)
    metadata={f['variable']:f for f in ((previous or {}).get('factors') or [])}
    previous_factors=[]
    for a in (previous or {}).get('assumptions',[]):
        if a['variable'] not in registry.factors:continue
        f={**metadata.get(a['variable'],{}),**a}
        f['role']='missing' if a['value'] is None else 'known'
        f.setdefault('relevant',True)
        previous_factors.append(f)
    selection=factor_selection.select(registry,question,reference_date=reference_date,timezone=timezone,
        history=history,profile=profile,previous=previous_factors,correction=correction)
    factors=[f.model_dump() for f in selection.factors]
    supplied={f['variable'] for f in factors}
    # A short clarification cannot erase earlier supplied facts. Explicit nulls
    # returned by the extractor can clear a value; new target is never an input.
    for f in previous_factors:
        if f['variable'] not in supplied and f['role']=='known' and f['variable']!=selection.target_variable:
            factors.append(dict(f))
    assumptions=[{k:f[k] for k in ('variable','value','unit','source','source_detail')} for f in factors]
    messages=list(history or [])
    messages.append({'role':'user','content':correction if correction is not None else question})
    response={'model':registry.model,'target_variable':selection.target_variable,'supporting_targets':selection.supporting_targets,'factors':factors,
        'assumptions':assumptions,'clarification_questions':[],
        'goal_summary':selection.goal_summary,'confidence_note':selection.confidence_note,
        'routing':decision.model_dump(exclude_defaults=True),
        'selection_state':{'model':registry.model,'revision':revision,'history':messages[-12:],'active_question':question,'reference_date':reference_date,'timezone':timezone}}
    return ExtractionResponse.model_validate(response).model_dump(exclude_unset=True)


def extract(user_message,reference_date,timezone,*,history=None,financial_profile=None):
    key=hashlib.sha256(json.dumps([user_message,reference_date,timezone,history or [],financial_profile or {}],sort_keys=True).encode()).hexdigest()
    with _ROUTE_LOCK:
        pending=PENDING_ROUTES.get(key)
        if pending and time.monotonic()-pending[0]>_ROUTE_TTL:
            PENDING_ROUTES.pop(key,None);pending=None
    decision=pending[1] if pending else model_router.route(user_message,history)
    if decision.model not in ('gap','ambiguous','multiple'):
        with _ROUTE_LOCK:
            PENDING_ROUTES[key]=(time.monotonic(),decision)
            PENDING_ROUTES.move_to_end(key)
            while len(PENDING_ROUTES)>_ROUTE_LIMIT:PENDING_ROUTES.popitem(last=False)
    # If extraction fails, UI Retry resumes this branch without routing again.
    result=_extract_branch(decision,user_message,reference_date,timezone,history=history,profile=financial_profile)
    with _ROUTE_LOCK:PENDING_ROUTES.pop(key,None)
    return result



def correct(user_message,reference_date,timezone,previous_extraction,user_correction,*,history=None,financial_profile=None):
    state=previous_extraction.get('selection_state',{})
    prior_model=state.get('model') or previous_extraction.get('model')
    prior_model={'bill_custom':'bill_split','bill_settlement':'bill_split'}.get(prior_model,prior_model)
    messages=list(history if history is not None else state.get('history',[]))
    import base_input_rules
    pending_question=base_input_rules.clarification_context(previous_extraction,state.get('active_question') or user_message,reference_date,timezone)
    if pending_question:messages.append(pending_question)
    previous_extraction,bound_reply=base_input_rules.bind_required_reply(previous_extraction,state.get('active_question') or user_message,user_correction,reference_date,timezone)
    active_question=state.get('active_question') or user_message
    pending=state.get('pending_transition')
    if not prior_model:
        decision=model_router.route(user_message+'\nUser clarification: '+user_correction,messages)
        return _extract_branch(decision,user_message,reference_date,timezone,history=messages,profile=financial_profile,
                               previous=previous_extraction,correction=user_correction)
    try:registry=get_registry(prior_model)
    except ValueError:raise HTTPException(422,'The previous model selection is invalid. Start a new question.') from None
    followup=(pending+'\nUser clarification: '+user_correction) if pending else user_correction
    if not pending and (bound_reply or intent_transition.ordinary_update(user_correction,registry)):
        decision=model_router.RoutingDecision(model=prior_model,transition='continuation')
    else:
        decision=model_router.route_followup(followup,current_model=prior_model,current_question=active_question,history=messages)
    if decision.model=='ambiguous':
        # Preserve the active question and its facts while awaiting intent clarity;
        # no new-question amounts enter factor state and no factor LLM runs.
        response=dict(previous_extraction)
        response['routing']=decision.model_dump(exclude_defaults=True)
        response['clarification_questions']=[{'target_variable':'model_selection','question':decision.clarification,
            'why_it_matters':'Clarify intent before changing the model or factors.'}]
        response['selection_state']={**state,'model':prior_model,'pending_transition':followup,'active_question':active_question}
        return response
    if decision.transition=='new' or decision.model in ('gap','multiple'):
        # New question, including a new question in the same model family: clear
        # old question factors and history before invoking its selected branch.
        return _extract_branch(decision,followup,reference_date,timezone,profile=financial_profile)
    return _extract_branch(decision,active_question,reference_date,timezone,history=messages,profile=financial_profile,
                           previous=previous_extraction,correction=followup)
