"""Resolved registry selection and deterministic, target-specific prerequisites.

No routing heuristics or financial calculation here. Missing alternatives produce
one question. Re-evaluation reuses Router and evidence-validated Extraction.
"""
import copy
import json
from decimal import Decimal
from factor_registry import get_registry
from dynamic_models import decode, SAVINGS_TARGETS


def question(variable, label):
    text_input = variable in ('target_selection','model_selection','split_method') or variable.endswith(
        ('entries','items','weights','paid','owed','participants','categories','adjustments'))
    return {'status':'needs_input', 'message':label,
            'missing_inputs':[{'variable':variable, 'label':label, 'input_type':'text' if text_input else 'number'}]}


def choose_input_option(group,values):
    # Prefer completing an already-supplied representation, e.g. income plus
    # spending, over asking for a new contribution when income is already known.
    return min(group,key=lambda names:(sum(values.get(n) is None for n in names),-sum(values.get(n) is not None for n in names)))


def input_question(name,calendar=False):
    return {
        'current_savings':'How much of your savings can you put toward this goal? You can say $0 if none.',
        'available_savings':'How much of your savings can you put toward this goal? You can say $0 if none.',
        'monthly_expenses':'About how much do you spend each month on rent, food, and everything else?',
        'monthly_income':'Roughly how much money comes in each month?',
        'monthly_contribution':'How much can you set aside each month after your expenses?',
        'monthly_surplus':'How much do you have left each month after all current expenses?',
        'goal_amount':'About how much will this goal cost?',
        'goal_deadline':'How many monthly deposits will you make before you need the money?',
        'contribution_months':'How many monthly deposits will you make before your stated deadline?',
    }.get(name,'What is your '+name.replace('_',' ')+'?')


def add_required_context(response,original_question):
    """Expose the selected target's unknown inputs before any final answer.

    This is the same registry/alternative selection used by resolve, not Grace's
    old universal savings checklist. Questions remain one per conversational turn.
    """
    import calendar_horizon
    response=calendar_horizon.annotate(response)
    model=response.get('model');target=response.get('target_variable')
    if not model or response.get('routing',{}).get('model') in ('gap','ambiguous','multiple'):return response
    registry=get_registry(model)
    if target not in registry.targets:return response
    factors={f['variable']:dict(f) for f in response.get('factors',[])}
    values={registry.aliases.get(a['variable'],a['variable']):decode(a['value']) for a in response.get('assumptions',[])
            if a['variable'] in registry.factors and a['variable']!=target and a.get('value') is not None and factors.get(a['variable'],{}).get('relevant',True)}
    if model=='savings_goal' and values.get('contribution_entries'):
        entries=values['contribution_entries']
        if len(entries)!=1 or any(e.get('frequency')!='monthly' for e in entries):return response
    if 'spending_entries' in values:
        import base_input_rules
        fact=next((a for a in response['assumptions'] if a['variable']=='spending_entries'),{})
        if not base_input_rules.complete_spending_evidence(original_question) and not base_input_rules.complete_spending_evidence(fact.get('source_detail','')):values.pop('spending_entries')
    calendar=False
    if model=='savings_goal' and values.get('goal_deadline') is not None:
        deadline=next((a for a in response['assumptions'] if registry.aliases.get(a['variable'],a['variable'])=='goal_deadline' and a.get('value') is not None),{})
        if isinstance(values['goal_deadline'],bool) or not isinstance(values['goal_deadline'],(int,float)) or deadline.get('unit') not in (None,'months'):
            values.pop('goal_deadline');calendar=True
    unknown=[]
    for group in registry.required_inputs(target,values):
        if any(all(values.get(n) is not None for n in option) for option in group):continue
        option=choose_input_option(group,values)
        if calendar and group == (('goal_deadline',),('contribution_months',)):option=('contribution_months',)
        unknown.extend(n for n in option if values.get(n) is None and n not in unknown)
    assumptions={a['variable']:dict(a) for a in response.get('assumptions',[])}
    for name,fact in factors.items():
        if fact.get('role')=='missing' and name!=target:fact['relevant']=name in unknown
    for name in unknown:
        unit='$/month' if name.startswith('monthly_') else 'months' if name in ('goal_deadline','contribution_months','payoff_months') else '$'
        fact=dict(variable=name,value=None,unit=unit,source='missing',source_detail='Required for the selected calculation; not provided.')
        assumptions[name]=fact;factors[name]={**fact,'role':'missing','relevant':True}
    result=copy.deepcopy(response)
    result.update(assumptions=list(assumptions.values()),factors=list(factors.values()),
        clarification_questions=[{'target_variable':n,'question':input_question(n,calendar),'why_it_matters':'Needed to answer your selected financial question.','required':True} for n in unknown])
    if unknown:
        result['assistant_message']='The items marked “Still unknown” are needed for this calculation. Let’s fill them in one at a time before I give a final answer.'
        if model=='savings_goal' and values.get('monthly_income') is not None and 'monthly_expenses' in unknown:
            result['assistant_message']='I know what you earn, but not how much is available after your expenses. I also need the other items marked “Still unknown” before I can answer. Let’s fill them in one at a time.'
    return result


def resolve(req, facts):
    meta = req.get('extraction_meta') or {}
    model = meta.get('model')
    routing = meta.get('routing') or {}
    if routing.get('model') == 'gap':
        return None, {'status':'unsupported','message':'This question is outside the four supported financial models.'}
    if routing.get('model') in ('ambiguous','multiple'):
        return None, question('model_selection', routing.get('clarification') or 'Which financial question would you like to address first?')
    # Old clients and reviewed slider scenarios retain their original contract.
    if not model: return None, None
    registry = get_registry(model)
    target = meta.get('target_variable')
    if target is None:
        return None, question('target_selection','What would you like to calculate for this question?')
    if target not in registry.targets:
        return None, question('target_selection','Which supported result would you like to calculate?')
    values = {}
    irrelevant = {f['variable'] for f in meta.get('factors',[]) if not f.get('relevant',True)}
    for name, fact in facts.items():
        if name in registry.factors and name not in irrelevant and name != target and fact.get('value') is not None:
            canonical = registry.aliases.get(name,name)
            value = decode(fact['value'])
            if canonical in values and values[canonical] != value:
                return None, question(name,'Which value should be used for '+canonical.replace('_',' ')+'?')
            values[canonical] = value
    if model=='savings_goal' and values.get('contribution_entries'):
        entries=values['contribution_entries']
        if len(entries)!=1 or any(e.get('frequency')!='monthly' for e in entries):
            return None, {'status':'unsupported','model':model,'target_variable':target,'message':'Exact nonmonthly deposit schedules are outside the current monthly savings model. The supplied schedule is complete; no additional user input is needed.','coverage_gaps':[{'reason':'Exact periodic deposit count is not supported by the monthly calculator.','supporting_facts':['contribution_entries']}]}
    if 'spending_entries' in values:
        import base_input_rules
        source=facts.get('spending_entries',{})
        if not base_input_rules.complete_spending_evidence(source.get('source_detail','')) and not base_input_rules.complete_spending_evidence(req.get('original_question','')):
            values.pop('spending_entries')
    # Calendar phrases are retained evidence, not an integer calculator horizon.
    calendar_deadline = None
    if model == 'savings_goal' and values.get('goal_deadline') is not None:
        deadline_fact = next((f for name,f in facts.items() if registry.aliases.get(name,name)=='goal_deadline' and f.get('value') is not None),{})
        deadline = values['goal_deadline']
        if isinstance(deadline,bool) or not isinstance(deadline,(int,float)) or deadline_fact.get('unit') not in (None,'months'):
            calendar_deadline = values.pop('goal_deadline')
    # Savings monthly_spending is canonicalized to monthly_expenses by its registry.
    for group in registry.required_inputs(target,values):
        if any(all(values.get(name) is not None for name in option) for option in group):continue
        option = choose_input_option(group,values)
        missing = next(n for n in option if values.get(n) is None)
        if calendar_deadline is not None and group == (('goal_deadline',), ('contribution_months',)):
            return None, question('contribution_months','How many monthly contributions will you make before your stated deadline?')
        if missing == 'monthly_surplus' and model == 'budget_cash_flow':
            return None, enrich_question(question(missing,'How much do you have left each month after all current expenses, including your current rent?'),model,target,values)
        response=question(missing,input_question(missing))
        return None, enrich_question(response,model,target,values)
    selection={'model':model,'target_variable':target,'definition':registry.selection_schema(),'supporting_targets':meta.get('supporting_targets',[])}
    selection['input_plan']=input_plan(model,target,facts)
    return selection, None


def matches(draft, selection):
    if draft.get('intent_mismatch'): return False
    model = draft.get('model')
    if model in ('bill_custom','bill_settlement'): model='bill_split'
    return model == selection['model'] and draft.get('target_variable') == selection['target_variable']


def primary_calculation_guide(selection):
    """Symbolic arithmetic plans only; Main evaluates all numbers itself."""
    plan=(selection or {}).get('input_plan',{})
    inputs=plan.get('inputs',{})
    if plan.get('model')=='savings_goal' and inputs.get('solve_for') in ('affordability','future_balance'):
        if inputs.get('monthly_savings') is not None:capacity=str(inputs['monthly_savings'])
        elif inputs.get('monthly_income') is not None:
            if inputs.get('monthly_spending') is not None:spending=str(inputs['monthly_spending'])
            elif inputs.get('spending_entries') and all(e.get('frequency','monthly')=='monthly' for e in inputs['spending_entries']):
                spending='('+' + '.join(str(e['amount']) for e in inputs['spending_entries'])+')'
            else:return None
            capacity=f"({inputs['monthly_income']} - {spending})"
        elif inputs.get('months')==0:capacity='0'
        else:return None
        balance=f"{inputs['current_savings']} + {capacity} * {inputs['months']}"
        return dict(projected_balance_expression=balance,
                    target_comparison=f"({balance}) >= {inputs['target']}" if 'target' in inputs else None,
                    instructions='Evaluate the supplied expression step by step. For affordability, compare the resulting balance with the price. Include monthly spending, monthly surplus and projected balance as derived factors where relevant. Do not solve inverse targets (required monthly saving or time to goal) unless the user separately asks them. Every displayed numeric equality must evaluate correctly.')
    if plan.get('model')!='bill_split' or inputs.get('method')!='itemized':return None
    terms={}
    for item in inputs.get('items',[])+inputs.get('shared_items',[]):
        owners=item.get('shared_by',[])
        for owner in owners:
            terms.setdefault(owner,[]).append(f"{item['amount']} / {len(owners)}")
    return {'pretax_subtotal_expressions':{owner:' + '.join(parts) for owner,parts in terms.items()},
            'instructions':'Evaluate each participant subtotal expression first. Add the subtotals. Allocate the supplied pooled tax/tip as charge * participant subtotal / sum of subtotals. Add that fee to that participant subtotal. Put the individual final values in amounts_owed. Show the numeric arithmetic in calculation. Do not divide the complete bill equally.'}


def validate_mode(draft, selection):
    if not matches(draft,selection):raise ValueError('Unresolved selection mismatch')
    model=selection['model']; target=selection['target_variable']; inputs=draft['inputs']
    if model=='savings_goal' and inputs.get('solve_for')!=SAVINGS_TARGETS[target]:
        raise ValueError('Savings target and solver disagree')
    if model=='debt_repayment':
        if target=='required_monthly_payment' and ('payoff_months' not in inputs or inputs.get('monthly_payment') is not None):
            raise ValueError('Debt target and solver disagree')
        if target=='estimated_payoff_months' and ('monthly_payment' not in inputs or inputs.get('payoff_months') is not None):
            raise ValueError('Debt target and solver disagree')
    if model=='bill_split' and target=='settlements' and not (draft['model']=='bill_settlement' or 'amounts_paid' in inputs):
        raise ValueError('Settlement target needs payments')
    registry=get_registry(model)
    if any(name not in registry.factors or name == target for name in draft.get('bindings',{}).values()):
        raise ValueError('A binding must reference a selected-model input, not its target')
    if any(f['variable'] not in registry.factors for f in draft.get('factors',[])):
        raise ValueError('Cross-model factor')


def reevaluate(req, facts, selection, draft):
    import model_router
    import extraction_service
    meta=req.get('extraction_meta') or {}
    state=meta.get('selection_state') or {}
    # Effective assumptions include user edits and additional numeric answers.
    # Give Router all retained evidence, never treat Main's proposal as user data.
    history=list(state.get('history') or [])
    history.append({'role':'user','content':json.dumps({'effective_user_facts':facts,'answers':req.get('answers',[])})})
    history.append({'role':'assistant','content':json.dumps({
        'reevaluation_requested':True,'previous_selection':selection['model'],
        'main_concern':draft.get('mismatch_reason','Model or target differs from the selected intent.'),
        'main_proposed_model':draft.get('model'),'main_proposed_target':draft.get('target_variable')})})
    decision=model_router.route(req['original_question'], history)
    # Only same-model facts may be retained as structured state. All original
    # evidence/corrections remain available for fresh, registry-specific extraction.
    previous=None
    if decision.model==selection['model']:
        previous={**meta,'assumptions':[{**v,'variable':k} for k,v in facts.items()],
                  'selection_state':state}
    extracted=extraction_service._extract_branch(decision,req['original_question'],
        state.get('reference_date',''),state.get('timezone',''),history=history,previous=previous)
    updated=copy.deepcopy(req)
    updated['extraction_meta']={k:v for k,v in extracted.items() if k not in ('assumptions','clarification_questions')}
    updated['assumptions']=extracted['assumptions']
    # Corrections with compatible IDs must survive even if the extractor repeats
    # an older literal. Incompatible fields cannot enter the new calculation.
    if extracted.get('model'):
        allowed=get_registry(extracted['model']).factors
        by_name={a['variable']:a for a in updated['assumptions']}
        for a in req['assumptions']:
            if a.get('edited_by_user') and a['variable'] in allowed and a['variable'] != extracted.get('target_variable'):
                by_name[a['variable']]=copy.deepcopy(a)
        for name, value in req.get('extra_inputs',{}).items():
            if name in allowed and name != extracted.get('target_variable'):
                by_name[name]=dict(variable=name, value=value, unit=facts[name].get('unit'), source='stated', source_detail='Entered by user', edited_by_user=True)
        updated['assumptions']=list(by_name.values())
        # Keep Main's metadata view consistent with the effective edited facts.
        factors={f['variable']:dict(f) for f in updated['extraction_meta'].get('factors',[])}
        for name, a in by_name.items():
            if not a.get('edited_by_user'):continue
            factors[name]={k:a.get(k) for k in ('variable','value','unit','source','source_detail')}
            factors[name].update(role='missing' if a['value'] is None else 'known',relevant=True)
        updated['extraction_meta']['factors']=list(factors.values())
    updated['extra_inputs']={}
    updated['parameters']={}
    return updated


def apply_intent_answer(req):
    answers=[a for a in req.get('answers',[]) if a['target_variable'] in ('target_selection','model_selection') and a.get('answer','').strip()]
    # The UI sends numeric missing-input answers through extra_inputs and prose
    # questions through answers. Accept either representation of intent text.
    for name in ('model_selection','target_selection'):
        if name in req.get('extra_inputs',{}):
            answers.append({'target_variable':name,'answer':str(req['extra_inputs'][name])})
    if not answers:return req
    import extraction_service
    meta=req.get('extraction_meta') or {}
    state=meta.get('selection_state') or {}
    previous={**meta,'assumptions':req['assumptions'],'clarification_questions':[],
              'goal_summary':meta.get('goal_summary','Financial question'),
              'confidence_note':meta.get('confidence_note','')}
    updated=copy.deepcopy(req)
    extracted=extraction_service.correct(req['original_question'],state.get('reference_date',''),
        state.get('timezone',''),previous,'\n'.join(a['answer'] for a in answers))
    updated['extraction_meta']={k:v for k,v in extracted.items() if k not in ('assumptions','clarification_questions')}
    updated['assumptions']=extracted['assumptions']
    updated['extra_inputs']={k:v for k,v in req.get('extra_inputs',{}).items() if k not in ('model_selection','target_selection')}
    updated['answers']=[a for a in req.get('answers',[]) if a not in answers]
    return updated


def enrich_question(response,model,target,values):
    response.update(model=model,target_variable=target)
    if model=='budget_cash_flow' and all(values.get(k) is not None for k in ('recurring_cost','replaced_recurring_cost')):
        difference=Decimal(str(values['recurring_cost']))-Decimal(str(values['replaced_recurring_cost']))
        # A supported intermediate result is independent of the unknown baseline.
        f=dict(variable='spending_change',value=float(difference),unit='$/month',role='derived',source='inferred',source_detail='New charge minus replaced charge.',supporting_facts=[{'factor_id':k,'value':values[k]} for k in ('recurring_cost','replaced_recurring_cost')])
        response['inferred_information']=[f]
        prefix=f'The replacement changes spending by ${difference:,.2f} per month. '
        response['message']=prefix+response['message']
        response['missing_inputs'][0]['label']=prefix+response['missing_inputs'][0]['label']
    return response


def input_plan(model,target,facts):
    """Select native representations without performing the primary math."""
    registry=get_registry(model)
    available={registry.aliases.get(k,k):(k,decode(f['value'])) for k,f in facts.items() if k in registry.factors and f.get('value') is not None}
    inputs={};bindings={}
    def add(native,*names):
        for name in names:
            if name in available:
                source,value=available[name];inputs[native]=value;bindings[native]=source;return True
        return False
    if model=='budget_cash_flow':
        if not add('monthly_surplus','monthly_surplus'):
            if not add('monthly_income','monthly_income') and not add('income_entries','income_entries'):
                add('fixed_income','fixed_income');add('variable_income','variable_income')
            if not add('monthly_spending','monthly_spending') and not add('spending_entries','spending_entries'):
                add('fixed_costs','fixed_costs');add('variable_costs','variable_costs')
        for name in ('income_change','spending_change_entries','expense_adjustments','expense_categories','replaced_recurring_cost'):add(name,name)
        if 'spending_change_entries' not in inputs:add('spending_change','recurring_cost','spending_change')
    elif model=='savings_goal':
        inputs['solve_for']=SAVINGS_TARGETS[target]
        add('current_savings','available_savings','current_savings');add('target','goal_amount')
        if target not in ('months_to_goal','goal_deadline'):add('months','contribution_months','goal_deadline')
        if target not in ('required_monthly_savings','monthly_contribution') and inputs.get('months')!=0:
            if not add('monthly_savings','monthly_contribution','monthly_surplus'):
                add('monthly_income','monthly_income')
                if not add('monthly_spending','monthly_expenses'):add('spending_entries','spending_entries')
    elif model=='bill_split':
        add('method','split_method');add('people','participants')
        if inputs.get('method')=='equal':add('total','total_bill')
        elif inputs.get('method')=='itemized':
            for native,name in [('items','items'),('shared_items','shared_items'),('tax','tax_amount'),('tip','tip_amount'),('tax_and_tip','tax_and_tip_amount')]:add(native,name)
        elif inputs.get('method') in ('custom','weighted'):
            inputs.pop('method',None);bindings.pop('method',None);inputs.pop('people',None);bindings.pop('people',None)
            add('total','total_bill');add('weights','split_weights')
        add('amounts_paid','amounts_paid')
    elif model=='debt_repayment':
        add('balance','principal_balance');add('apr','apr')
        if target=='required_monthly_payment':add('payoff_months','payoff_months')
        elif target!='monthly_interest':
            if not add('monthly_payment','monthly_payment'):add('payoff_months','payoff_months')
    native_model=model
    if model=='bill_split':
        if 'weights' in inputs:native_model='bill_custom'
        elif target=='settlements' and 'amounts_owed' in available:
            native_model='bill_settlement';inputs={};bindings={}
            add('amounts_owed','amounts_owed');add('amounts_paid','amounts_paid')
    return {'model':native_model,'inputs':inputs,'bindings':bindings,'note':'Use these raw source values and exact bindings; perform your own primary calculation. Do not invent optional zero inputs or anonymous names.'}
