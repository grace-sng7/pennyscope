"""Optional factor/target protocol. LLM selects roles and target; Python verifies.

No new financial models or UI code generation. This adapts the same existing
calculator functions to reversible questions and read-only result factors.
"""
import inspect
import json
from decimal import Decimal

from contract import ModelFactor
from financial_tools import (calculate_savings, calculate_cash_flow, split_bill,
                             split_custom, settle_payments, calculate_debt_repayment, monthly)

TOOLS = {'savings_goal': calculate_savings, 'budget_cash_flow': calculate_cash_flow,
         'bill_split': split_bill, 'bill_custom': split_custom,
         'bill_settlement': settle_payments, 'debt_repayment': calculate_debt_repayment}
SAVINGS_TARGETS = {'affordability_status':'affordability','shortfall':'affordability',
                   'projected_savings':'future_balance','required_monthly_savings':'monthly_required',
                   'monthly_contribution':'monthly_required','months_to_goal':'months_required',
                   'goal_deadline':'months_required'}
ALIASES = {'monthly_expenses':'monthly_spending','target_amount':'target','goal_amount':'target','monthly_contribution':'monthly_savings',
           'goal_deadline':'months','months_to_goal':'months_required',
           'affordability_status':'affordable','projected_surplus':'scenario_monthly_surplus',
           'total_bill':'total','participants':'people','split_method':'method',
           'tax_amount':'tax','tip_amount':'tip','split_weights':'weights',
           'settlements':'transfers','principal_balance':'balance','apr':'apr_percent',
           'monthly_interest':'first_month_interest','estimated_payoff_months':'payoff_months'}


def decode(value):
    if isinstance(value,str):
        try:return json.loads(value)
        except ValueError:pass
    return value


def same(a,b):
    if isinstance(a,bool) or isinstance(b,bool):return a is b
    try:return Decimal(str(a))==Decimal(str(b))
    except Exception:return a==b


def validate(draft, facts):
    model=draft['model']; inputs=draft['inputs']; target=draft['target_variable']
    if model not in TOOLS or not isinstance(inputs,dict) or not isinstance(target,str):
        raise ValueError('Unknown model or target')
    allowed=set(inspect.signature(TOOLS[model]).parameters)
    if model=='budget_cash_flow':allowed.update(('expense_adjustments','spending_change_entries'))
    if model in ('bill_split','bill_custom'):allowed.update(('amounts_paid','shared_items'))
    if set(inputs)-allowed:raise ValueError('Unknown calculator input')
    for name,value in inputs.items():
        if model=='savings_goal' and name=='solve_for':
            if SAVINGS_TARGETS.get(target)!=value:raise ValueError('Target and calculation mode disagree')
            continue
        fact=facts.get(draft.get('bindings',{}).get(name,name))
        if value is None: # optional absent argument, not an invented zero
            parameter=inspect.signature(TOOLS[model]).parameters.get(name)
            if parameter and parameter.default is None:continue
        if not fact or fact['value'] is None or not same(value,decode(fact['value'])):
            raise ValueError('Input differs from supporting evidence')
        expected={'monthly_income':'$/month','monthly_spending':'$/month','monthly_payment':'$/month',
                  'balance':'$','current_savings':'$','target':'$','total':'$', 'tax':'$','tip':'$',
                  'monthly_savings':'$/month','spending_change':'$/month','income_change':'$/month','months':'months','payoff_months':'months'}.get(name)
        if expected and fact.get('unit') not in (None,expected):raise ValueError('Incompatible units')
    if model=='savings_goal':
        # Never let the verifier's default turn unknown savings into zero.
        if 'current_savings' not in inputs:raise ValueError('Starting savings must be explicit')
        if 'monthly_savings' not in inputs and inputs.get('solve_for') in ('future_balance','affordability','months_required'):
            if inputs.get('monthly_income') is None or inputs.get('monthly_spending') is None:
                raise ValueError('Contribution or income and spending are required')
    if model=='budget_cash_flow':
        # The existing tool supports optional bucket components; require both when
        # choosing bucket form so unavailable amounts never become implicit zero.
        for pair in [('fixed_income','variable_income'),('fixed_costs','variable_costs')]:
            if any(k in inputs for k in pair) and any(inputs.get(k) is None for k in pair):
                raise ValueError('A bucket amount is missing')
    for f in draft.get('factors',[]):ModelFactor.model_validate(f)
    if len({f['variable'] for f in draft.get('factors',[])})!=len(draft.get('factors',[])):
        raise ValueError('Duplicate factors')
    if target not in {f['variable'] for f in draft.get('factors',[])}:
        raise ValueError('Target factor absent')


def verify(draft):
    model=draft['model']; inputs=dict(draft['inputs'])
    if model=='budget_cash_flow' and 'spending_change_entries' in inputs:
        if 'spending_change' in inputs:raise ValueError('Choose raw periodic changes or a monthly change, not both')
        entries=inputs.pop('spending_change_entries')
        if not isinstance(entries,list) or not entries:raise ValueError('Periodic changes need explicit entries')
        inputs['spending_change']=sum((monthly(e['amount'],e['frequency']) for e in entries),Decimal(0))
    if model=='budget_cash_flow' and 'expense_adjustments' in inputs:
        adjustments=inputs.pop('expense_adjustments')
        if not isinstance(adjustments,list) or len({a['name'] for a in adjustments})!=len(adjustments):
            raise ValueError('Invalid adjustments')
        categories=[dict(c) for c in inputs.get('expense_categories',[])]
        by_name={c['name']:c for c in categories}
        for a in adjustments:
            if a['name'] not in by_name:raise ValueError('Unknown expense category')
            if by_name[a['name']].get('proposed_reduction',0):raise ValueError('Duplicate adjustment')
            by_name[a['name']]['proposed_reduction']=a['proposed_reduction']
        inputs['expense_categories']=categories
    paid=inputs.pop('amounts_paid',None) if model in ('bill_split','bill_custom') else None
    shared=inputs.pop('shared_items',None) if model in ('bill_split','bill_custom') else None
    if shared:
        if model!='bill_split' or inputs.get('method')!='itemized':raise ValueError('Shared items need itemized allocation')
        inputs['items']=[*inputs.get('items',[]),*shared]
    result=TOOLS[model](**inputs)
    if model=='budget_cash_flow':result['affordable']=Decimal(result['scenario_monthly_surplus'])>=0
    if paid is not None:result.update(settle_payments(result['amounts_owed'],paid))
    if model=='debt_repayment' and result.get('total_interest') is not None:
        result['total_repayment']=str((Decimal(str(inputs['balance']))+Decimal(result['total_interest'])).quantize(Decimal('.01')))
    return result


def resolved_factors(draft, actual, facts):
    combined={**draft['inputs'],**actual}
    # The main LLM may name the solved deadline or contribution using existing
    # factor names. Role is determined by this question, not the variable name.
    if draft['model']=='savings_goal':
        if draft['inputs']['solve_for']=='months_required':combined['months']=actual.get('months_required')
        if draft['inputs']['solve_for']=='monthly_required':combined['monthly_savings']=actual.get('required_monthly_savings')
    factors=[]
    for entry in draft['factors']:
        f=dict(entry); name=f['variable']
        if f['role']=='known':
            fact=facts.get(name)
            if not fact or not same(decode(f['value']),decode(fact['value'])):
                raise ValueError('Known factor lacks evidence')
            f.update(value=fact['value'],source=fact['source'],source_detail=fact['source_detail'])
        elif f['role']=='derived':
            key=name if name in actual else ALIASES.get(name,name)
            value=combined.get(key)
            if value is None:
                if name==draft['target_variable'] and draft['model']=='savings_goal' and actual.get('feasible') is False:
                    value='Not reachable with the reviewed monthly contribution'
                elif name==draft['target_variable'] and draft['model']=='debt_repayment' and actual.get('payoff_possible') is False:
                    value='Not repayable with the reviewed monthly payment'
                else:raise ValueError('Derived factor has no independent verification')
            if isinstance(value,bool):value='Yes' if value else 'No'
            elif isinstance(value,(dict,list)):value=json.dumps(value)
            elif isinstance(value,str):
                try:
                    number=Decimal(value)
                    if number.is_finite():value=float(number)
                except Exception:pass
            f.update(value=value,source='inferred',source_detail='Independently verified from the reviewed inputs and model assumptions.')
        factors.append(ModelFactor.model_validate(f).model_dump())
    if next(f for f in factors if f['variable']==draft['target_variable'])['role']!='derived':
        raise ValueError('A completed answer must resolve its target')
    return factors


def present(draft, actual, review, facts):
    factors=resolved_factors(draft,actual,facts)
    target=next(f for f in factors if f['variable']==draft['target_variable'])
    value=target['value'];unit=target.get('unit') or ''
    shown=f'${value:,.2f}' if isinstance(value,(int,float)) and unit.startswith('$') else str(value)
    if unit and unit not in ('$','text') and not isinstance(value,str):shown+=(' / month' if unit=='$/month' else ' '+unit)
    title=draft['target_variable'].replace('_',' ').capitalize()
    formulas={'savings_goal':{'future_balance':'Projected savings = starting savings + monthly contribution × months.',
                              'affordability':'Compare starting savings + monthly contribution × months with the target amount.',
                              'monthly_required':'Required monthly savings = max(0, target − starting savings) ÷ months, rounded up to cents.',
                              'months_required':'Months to goal = ceil(max(0, target − starting savings) ÷ monthly contribution).'},
              'budget_cash_flow':'Monthly surplus = monthly income − monthly spending. Projected surplus applies only the reviewed adjustments.',
              'bill_split':'Use the agreed allocation rule, reconcile cents, then compare amounts owed with amounts paid.',
              'bill_custom':'Each share = total × agreed weight ÷ total weights; reconcile cents.',
              'bill_settlement':'Net balance = amount paid − amount owed; transfers reconcile the balances.',
              'debt_repayment':'Monthly interest = outstanding principal × APR ÷ 1200; apply the reviewed payment until paid off.'}
    formula=formulas[draft['model']]
    if isinstance(formula,dict):formula=formula[draft['inputs']['solve_for']]
    return {'status':'conditional','model':draft['model'],'target_variable':draft['target_variable'],'factors':factors,
            'answer':{'headline':title+': '+('See the breakdown below.' if str(value).startswith(('[','{')) else shown),
                      'detail':review.get('detail','Based on the reviewed factors and assumptions.')},
            'metrics':[],'parameters':[], 'explanations':[{'label':'Verified calculation','text':formula}],
            'assumptions':[{'text':s} for s in review.get('assumptions',[])],
            'limitations':['Results use the reviewed factors and model assumptions.'] + (['Periodic amounts are annualized to monthly averages; actual payment-date cash flow can differ.'] if draft['model']=='budget_cash_flow' else [])}
