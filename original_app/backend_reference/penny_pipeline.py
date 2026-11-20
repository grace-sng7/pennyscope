"""Penny Scope decision path (see "Penny Scope _ Formula and Exemplar Review").

1. classify: the LLM decides whether the question is one of the four financial
   models (budget_cash_flow, savings_goal, bill_split, debt_repayment) or none.
2. If it is one of the four:
   - extract: the LLM pulls out that model's inputs and the requested target.
   - Python decides which inputs the target still needs; one question at a time.
   - calculate: Python runs that model's spreadsheet formulas (financial_tools).
     The LLM only explains the computed numbers; it never does the arithmetic.
3. If it is none of the four: free thinking. The LLM answers directly.

Responses keep the existing /extract, /correct, /calculate wire shapes.
"""
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

try:
    import financial_tools as ft
except ImportError:  # local checkout: the calculator lives at the repository root
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    import financial_tools as ft

import gemini_gateway

M, D, MONTHS, PCT, TEXT = '$/month', '$', 'months', '%', None

# Inputs per model: variable -> (unit, description shown to the extraction LLM).
# Variable IDs follow the spreadsheet's backend factor IDs.
MODELS = {
    'budget_cash_flow': dict(
        title='Budget & Cash Flow',
        use_when='How ongoing (recurring) income and spending affect the monthly budget: money left each month, '
                 'or whether a new or changed recurring cost (rent, a plan, a subscription) fits.',
        formulas=['Monthly Surplus = Monthly Income - Monthly Spending.',
                  'Projected Monthly Surplus = Current Monthly Surplus + Change in Monthly Income - Change in Monthly Spending.',
                  'Replacing a recurring charge: Change in Monthly Spending = New Charge - Old Charge.'],
        inputs={
            'monthly_income': (M, 'Total take-home income per month.'),
            'monthly_spending': (M, 'TOTAL monthly spending on everything. Never a single expense or a partial list.'),
            'monthly_surplus': (M, 'Amount the user says is left each month after all current expenses.'),
            'expense_items': (TEXT, 'Individual expenses mentioned, as a list [{"name","amount","frequency"}]. Not a total.'),
            'recurring_cost': (D, 'Proposed new ongoing charge, per its billing period.'),
            'recurring_cost_frequency': (TEXT, 'weekly, biweekly, semimonthly, monthly, quarterly or annually. Infer monthly for rent, phone plans, subscriptions.'),
            'replaced_recurring_cost': (D, 'Existing charge that the new recurring_cost replaces (e.g. current rent).'),
            'spending_change': (M, 'Stated change in monthly spending: positive increase, negative decrease.'),
            'income_change': (M, 'Stated change in monthly income: positive raise, negative cut.'),
        },
        targets=['monthly_surplus', 'projected_surplus', 'affordability_status']),
    'savings_goal': dict(
        title='Savings Projection / One Time Affordability',
        use_when='Whether available funds can cover a one-time purchase or reach a savings goal: projected savings, '
                 'required monthly saving, months to a goal, or affordability of a purchase (today or later). '
                 'A monthly contribution toward a one-time goal still belongs here.',
        formulas=['Projected Savings = Available Savings + Monthly Contribution x Number of Months.',
                  'Required Monthly Contribution = max(0, Goal Amount - Available Savings) / Months, rounded up to the cent.',
                  'Months to Goal = max(0, Goal Amount - Available Savings) / Monthly Contribution, rounded up.',
                  'Shortfall = max(0, Goal Amount - Projected Savings). A purchase today has zero future contributions.'],
        inputs={
            'available_savings': (D, 'Money already set aside or available for THIS goal.'),
            'goal_amount': (D, 'Purchase price or savings target.'),
            'months': (MONTHS, 'Whole months until the goal or purchase; 0 means today. Convert a calendar date using the reference date (mark inferred).'),
            'monthly_contribution': (M, 'Amount added each month toward the goal.'),
            'monthly_income': (M, 'Monthly income, only if the contribution must come from income minus spending.'),
            'monthly_spending': (M, 'Total monthly spending, only alongside monthly_income.'),
            'deposit_amount': (D, 'Amount per deposit when deposits are NOT monthly (e.g. weekly).'),
            'deposit_frequency': (TEXT, 'Frequency of those deposits, e.g. weekly.'),
            'deposit_count': ('deposits', 'Number of those deposits.'),
            'goal_description': (TEXT, 'Short description of the goal, e.g. trip, laptop.'),
        },
        targets=['projected_savings', 'required_monthly_savings', 'months_to_goal', 'affordability_status']),
    'bill_split': dict(
        title='Bill Splitting',
        use_when='Dividing a shared bill or expense among people, reimbursements, and who owes whom.',
        formulas=['Equal Split = Total Bill / Number of People (cents reconciled to the total).',
                  'Itemized: each item split among the people who shared it; tax and tip split in proportion to each pretax share.',
                  'Weighted Split = Total Bill x Each Person\'s Weight / Sum of Weights.',
                  'Net Settlement Balance = Amount Already Paid - Amount Owed; people below zero pay people above zero.'],
        inputs={
            'total_bill': (D, 'Total amount to divide (all-inclusive if the user says tax and tip are included).'),
            'participants': (TEXT, 'Either a number of people, or a list of names. Use "me" for the user.'),
            'split_method': (TEXT, 'equal, itemized or weighted. Item assignments imply itemized. "Ordered different things" alone does NOT set a method.'),
            'items': (TEXT, 'Itemized only: list [{"name","amount","shared_by":[names]}]. A shared item lists everyone who shared it.'),
            'tax_amount': (D, 'Tax not already in the item prices. 0 if the user says no tax.'),
            'tip_amount': (D, 'Tip not already in the item prices. 0 if the user says no tip.'),
            'split_weights': (TEXT, 'Weighted only: object {"name": weight}.'),
            'amounts_paid': (TEXT, 'Object {"name": amount} of what each person already paid. If one person paid the whole bill, everyone else paid 0.'),
        },
        targets=['amounts_owed', 'settlements']),
    'debt_repayment': dict(
        title='Basic Debt Repayment',
        use_when='Loans or credit card balances: monthly interest, payoff time, required monthly payment, total interest or total repayment.',
        formulas=['Monthly Interest Rate = APR / 12 (APR as a percent: / 1200).',
                  'Each month: interest = opening balance x monthly rate; then subtract the payment (smaller final payment).',
                  'Months to Pay Off = number of months until the balance reaches zero.',
                  'Required Monthly Payment = Principal x r / (1 - (1 + r)^-n), rounded up to the cent; at 0% APR, Principal / n.',
                  'Total Repayment = Principal + Total Interest.'],
        inputs={
            'principal_balance': (D, 'Amount owed now.'),
            'apr': (PCT, 'Annual percentage rate as a percent number: 12% is 12. 0 if the user says 0% or no interest.'),
            'monthly_payment': (M, 'Payment the user makes or plans each month.'),
            'payoff_months': (MONTHS, 'Desired number of months to pay it off.'),
        },
        targets=['estimated_payoff_months', 'required_monthly_payment', 'monthly_interest', 'total_interest', 'total_repayment']),
}

TARGET_UNITS = {'monthly_surplus': M, 'projected_surplus': M, 'affordability_status': TEXT, 'projected_savings': D,
                'required_monthly_savings': M, 'months_to_goal': MONTHS, 'shortfall': D, 'amounts_owed': TEXT,
                'settlements': TEXT, 'estimated_payoff_months': MONTHS, 'required_monthly_payment': M,
                'monthly_interest': D, 'total_interest': D, 'total_repayment': D, 'spending_change': M}

# One focused question per missing input (wording from the exemplar sheet where given).
QUESTIONS = {
    'monthly_income': 'How much do you take home each month?',
    'monthly_spending': 'About how much do you spend in total each month, including everything you mentioned?',
    'monthly_surplus': 'How much do you usually have left each month after paying your current expenses?',
    'spending_change': 'How much would your monthly spending change?',
    'available_savings': 'How much money do you already have set aside for this?',
    'goal_amount': 'How much does it cost, or how much do you want to have?',
    'months': 'How many months from now do you need the money?',
    'monthly_contribution': 'How much can you put toward this each month?',
    'split_method': 'Do you want to split it evenly or by what each person ordered?',
    'total_bill': 'What was the total bill?',
    'participants': 'How many people are splitting it, or who are they?',
    'items': 'What did each person order, and how much was each item?',
    'split_weights': 'What share should each person pay?',
    'amounts_paid': 'Who has already paid, and how much?',
    'principal_balance': 'How much do you owe right now?',
    'apr': 'What’s the APR on that balance?',
    'monthly_payment': 'How much can you pay each month?',
    'payoff_months': 'How many months do you want to pay it off in?',
}


# ------------------------------------------------------------------ LLM calls
CLASSIFY_PROMPT = '''You decide which Penny Scope financial model a user's question belongs to.
Choose by the user's intent, not keywords. The models:
{models}
If the question fits none of them (e.g. investing, taxes, dated cash timing, general money advice),
return "none". Missing numbers are NOT a reason for "none": still choose the model.
When an active question is given, a follow-up that only supplies or changes facts, or asks a
what-if about it, keeps the active model.
Also give a one-sentence reason the user can read, e.g. "You're asking whether savings plus monthly
leftover can cover a one-time purchase by a date."
Return JSON only: {{"model": "budget_cash_flow" | "savings_goal" | "bill_split" | "debt_repayment" | "none", "reason": "..."}}'''

EXTRACT_PROMPT = '''You extract inputs for the Penny Scope "{title}" model. Do NOT calculate anything.
Model use: {use_when}
Inputs you may fill (variable: unit, meaning):
{inputs}
Targets (the result the user wants): {targets}
Rules:
- Pick target = the single result the user asks for; supporting_targets = any other listed targets they ALSO ask for.
- Only include inputs the user gave or that follow directly from their words. Never guess personal finances.
  Unknown inputs are simply left out.
- how="stated" for a value said outright, "inferred" for one that follows from context (say why in note).
- Money is a plain number (no $). Percent as a number (12% -> 12). Lists/objects as JSON values.
- Latest corrections override earlier facts. Answers to a question fill the input that question asked for.
Return JSON only: {{"target": "...", "supporting_targets": [], "facts": [{{"variable": "...", "value": ..., "how": "stated"|"inferred", "note": "short quote or reason"}}], "summary": "one sentence restating the goal"}}'''

FREE_PROMPT = '''You are Penny Scope, a friendly personal finance helper. This question is outside the four
calculators (budget, savings, bill splitting, debt), so think it through freely, using the user's numbers.
If a personal fact you truly need is missing, ask ONE short question instead.
Plain text only: no markdown, no asterisks, no headings, no tables, no JSON. Lay an answer out in this order:
a one or two sentence answer; a blank line; "Assumptions:" then each assumption on its own line starting
with "- "; a blank line; "Steps:" then numbered lines ("1. ", "2. ") showing how you reasoned, with any
arithmetic written out. Keep it under 200 words. You are not a licensed advisor; avoid specific
investment recommendations.
Start with exactly ANSWER: or QUESTION:, then your reply.'''

EXPLAIN_PROMPT = '''You explain a finished Penny Scope calculation to the user in 2-4 short, friendly sentences
(second person). Use ONLY the numbers given in "results" and "inputs"; never compute or introduce new numbers.
Then give 2 short what-if follow-ups the user might type, each changing one input.
Return JSON only: {"text": "...", "suggestions": ["...", "..."]}'''


def _call_json(system, payload, stage, schema):
    return gemini_gateway.call_json(system, json.dumps(payload, default=str), stage=stage, response_schema=schema)


def route(question, *, active_model=None, active_question=None):
    """Which model fits, and a short reason the UI can show."""
    models = '\n'.join(f'- {k}: {v["use_when"]}' for k, v in MODELS.items())
    schema = {'type': 'object', 'properties': {'model': {'type': 'string', 'enum': [*MODELS, 'none']},
                                               'reason': {'type': 'string'}}, 'required': ['model']}
    payload = {'question': question}
    if active_model:
        payload.update(active_model=active_model, active_question=active_question)
    raw = _call_json(CLASSIFY_PROMPT.format(models=models), payload, 'model_routing', schema)
    model = raw.get('model') if raw.get('model') in MODELS else 'none'
    reason = raw.get('reason') if isinstance(raw.get('reason'), str) else ''
    return route_info(model, reason.strip())


def classify(question, **kwargs):
    return route(question, **kwargs)['model']


def route_info(model, reason=''):
    """The match shown to the user: one of the four models, or free thinking."""
    if model in MODELS:
        return dict(path='model', model=model, title=MODELS[model]['title'],
                    reason=reason or f'This question fits the {MODELS[model]["title"]} model.')
    return dict(path='free', model='none', title='Free thinking',
                reason=reason or 'This question doesn’t fit one of the four calculators, so I reasoned it out directly.')


def _extract_raw(model, question, *, reference_date, correction=None, previous=None, profile=None):
    spec = MODELS[model]
    inputs = '\n'.join(f'- {k}: {u or "text"}, {d}' for k, (u, d) in spec['inputs'].items())
    system = EXTRACT_PROMPT.format(title=spec['title'], use_when=spec['use_when'], inputs=inputs, targets=', '.join(spec['targets']))
    schema = {'type': 'object', 'properties': {
        'target': {'type': 'string', 'enum': spec['targets']},
        'supporting_targets': {'type': 'array', 'items': {'type': 'string'}},
        'facts': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'variable': {'type': 'string'}, 'value': {}, 'how': {'type': 'string', 'enum': ['stated', 'inferred']},
            'note': {'type': 'string'}}, 'required': ['variable', 'value', 'how']}},
        'summary': {'type': 'string'}}, 'required': ['target', 'facts']}
    payload = {'question': question, 'reference_date': reference_date}
    if previous:
        payload['previous_facts'] = {k: v['value'] for k, v in previous.items()}
    if correction:
        payload['latest_user_message'] = correction
    if profile:
        payload['financial_profile'] = profile
    return _call_json(system, payload, 'factor_extraction', schema)


def free_think(question, facts=(), correction=None):
    """Default path when no model fits: the LLM reasons the answer out directly."""
    payload = {'question': question, 'latest_user_message': correction,
               'known_facts': {f['variable']: f['value'] for f in facts if f.get('value') is not None}}
    try:
        text = gemini_gateway.call_text(FREE_PROMPT, json.dumps(payload, default=str), stage='chat_fallback').strip()
    except Exception:
        return {'kind': 'limitation', 'text': 'I couldn’t work this one out right now. Please try again.'}
    kind = 'answer'
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text).replace('**', '')      # the chat shows plain text
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.M)
    for label in ('ANSWER:', 'QUESTION:'):
        if text.upper().startswith(label):
            kind, text = label[:-1].lower(), text[len(label):].strip()
    return {'kind': kind, 'text': text or 'I couldn’t work this one out right now. Please try again.'}


# ------------------------------------------------------------- fact handling
def _number(value):
    if isinstance(value, bool):
        raise ValueError
    n = ft.D(str(value).replace(',', '').replace('$', '').replace('%', '').strip())
    return int(n) if n == n.to_integral_value() else float(n)


def _clean(model, raw_facts):
    """Keep only this model's inputs, with the expected value types."""
    spec = MODELS[model]['inputs']
    facts = {}
    for item in raw_facts or []:
        name, value = item.get('variable'), item.get('value')
        if name not in spec or value is None or value == '':
            continue
        unit = spec[name][0]
        try:
            if unit is None:
                if name == 'participants' and not isinstance(value, (list, str)):
                    value = _number(value)
                elif isinstance(value, (list, dict)):
                    value = json.dumps(value)
                else:
                    value = str(value).strip().lower() if name in ('split_method', 'recurring_cost_frequency', 'deposit_frequency') else str(value)
            else:
                value = _number(value)
                if name not in ('spending_change', 'income_change') and value < 0:
                    continue
        except (ValueError, ArithmeticError, TypeError):
            continue
        source = 'inferred' if item.get('how') == 'inferred' else 'stated'
        note = (item.get('note') or '').strip()
        facts[name] = dict(variable=name, value=value, unit=unit, source=source,
                           source_detail=(('From your message: ' if source == 'stated' else 'Inferred: ') + note) if note else
                           ('From your message' if source == 'stated' else 'Inferred from context'))
    return facts


def _decoded(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _people(facts):
    value = _decoded(facts.get('participants', {}).get('value'))
    if isinstance(value, list) and value:
        return [str(p) for p in value]
    if isinstance(value, (int, float)) and value >= 1 and value == int(value):
        return [f'Person {i + 1}' for i in range(int(value))]
    items = _decoded(facts.get('items', {}).get('value'))
    if isinstance(items, list):
        names = [str(p) for item in items if isinstance(item, dict) for p in item.get('shared_by', [])]
        return list(dict.fromkeys(names)) or None
    return None


def _has(facts, *names):
    return all(facts.get(n, {}).get('value') is not None for n in names)


def missing_inputs(model, target, facts, supporting=()):
    """Inputs the requested target(s) still need, in the order to ask them."""
    need = []
    def want(*alternatives):
        # alternatives: tuples of variables; satisfied if any tuple is complete
        if not any(_has(facts, *alt) for alt in alternatives):
            need.append(next(n for n in alternatives[0] if not _has(facts, n)))
    targets = [target, *supporting]
    if model == 'budget_cash_flow':
        if 'monthly_surplus' in targets and not _has(facts, 'monthly_surplus'):
            want(('monthly_income', 'monthly_spending'))
        if {'projected_surplus', 'affordability_status'} & set(targets):
            want(('recurring_cost',), ('spending_change',), ('income_change',))
            want(('monthly_surplus',), ('monthly_income', 'monthly_spending'))
    elif model == 'savings_goal':
        want(('available_savings',))
        today = facts.get('months', {}).get('value') == 0
        contribution = (('monthly_contribution',), ('monthly_income', 'monthly_spending'))
        for t in targets:
            if t == 'projected_savings':
                if not _has(facts, 'deposit_amount', 'deposit_count'):
                    want(('months',))
                    if not today: want(*contribution)
            elif t == 'required_monthly_savings':
                want(('goal_amount',)); want(('months',))
            elif t == 'months_to_goal':
                want(('goal_amount',)); want(*contribution)
            elif t == 'affordability_status':
                want(('goal_amount',)); want(('months',))
                if not today: want(*contribution)
    elif model == 'bill_split':
        want(('split_method',))
        method = facts.get('split_method', {}).get('value')
        if method == 'equal':
            want(('total_bill',)); want(('participants',))
        elif method == 'itemized':
            want(('items',))
        elif method == 'weighted':
            want(('total_bill',)); want(('split_weights',))
        if 'settlements' in targets:
            want(('amounts_paid',))
    elif model == 'debt_repayment':
        want(('principal_balance',)); want(('apr',))
        for t in targets:
            if t == 'estimated_payoff_months':
                want(('monthly_payment',))
            elif t == 'required_monthly_payment':
                want(('payoff_months',))
            elif t in ('total_interest', 'total_repayment'):
                want(('monthly_payment',), ('payoff_months',))
    return list(dict.fromkeys(need))


# ------------------------------------------------------------ /extract, /correct
def _extraction_response(model, target, supporting, facts, question, summary, history, matched=None):
    spec = MODELS[model]
    missing = missing_inputs(model, target, facts, supporting)
    assumptions = list(facts.values()) + [
        dict(variable=n, value=None, unit=spec['inputs'][n][0], source='missing', source_detail='Still needed for this calculation.')
        for n in missing]
    factors = [dict(**{k: f[k] for k in ('variable', 'value', 'unit', 'source', 'source_detail')},
                    role='missing' if f['value'] is None else 'known', relevant=True) for f in assumptions]
    factors.append(dict(variable=target, value=None, unit=TARGET_UNITS.get(target), role='missing', source='missing',
                        source_detail='The result you asked for.', relevant=True))
    return dict(
        assumptions=assumptions,
        clarification_questions=[dict(target_variable=n, question=QUESTIONS.get(n, f'What is your {n.replace("_", " ")}?'),
                                      why_it_matters=f'Needed for the {spec["title"]} calculation.', required=True) for n in missing],
        goal_summary=summary or f'{spec["title"]}: {target.replace("_", " ")}.',
        confidence_note='Calculated with the ' + spec['title'] + ' formulas once every required input is known.',
        model=model, target_variable=target, supporting_targets=supporting, factors=factors,
        route=matched or route_info(model),
        selection_state=dict(model=model, active_question=question, history=history[-12:]))


def _free_response(question, facts, correction=None, history=(), matched=None):
    return dict(route=matched or route_info('none'), assumptions=list(facts.values()) if isinstance(facts, dict) else [], clarification_questions=[],
                goal_summary='Thinking this through without a fixed formula.',
                confidence_note='No Penny Scope model fits this question, so this is a free-form answer.',
                selection_state=dict(model=None, active_question=question, history=list(history)[-12:]),
                chat_fallback=free_think(question, list(facts.values()) if isinstance(facts, dict) else [], correction))


def extract(question, reference_date, *, profile=None):
    history = [{'role': 'user', 'content': question}]
    matched = route(question)
    model = matched['model']
    if model == 'none':
        return _free_response(question, {}, history=history, matched=matched)
    raw = _extract_raw(model, question, reference_date=reference_date, profile=profile)
    return _from_raw(model, raw, {}, question, history, matched)


def _from_raw(model, raw, previous, question, history, matched=None):
    target = raw.get('target') if raw.get('target') in MODELS[model]['targets'] else MODELS[model]['targets'][0]
    supporting = [t for t in raw.get('supporting_targets') or [] if t in MODELS[model]['targets'] and t != target]
    facts = {**previous, **_clean(model, raw.get('facts'))}
    return _extraction_response(model, target, supporting, facts, question, raw.get('summary'), history, matched)


def correct(question, reference_date, previous_extraction, correction, *, profile=None):
    state = previous_extraction.get('selection_state') or {}
    history = [*(state.get('history') or [{'role': 'user', 'content': question}]), {'role': 'user', 'content': correction}]
    active = previous_extraction.get('model') if previous_extraction.get('model') in MODELS else None
    matched = route(correction, active_model=active, active_question=question)
    model = matched['model']
    if model == active and previous_extraction.get('route'):
        matched = previous_extraction['route']  # same question: keep the original match and its reason
    previous = {a['variable']: a for a in previous_extraction.get('assumptions', []) if a.get('value') is not None}
    if model == 'none':
        return _free_response(question, previous, correction, history, matched)
    if model != active:  # a new question: start fresh with its own model
        question, previous, history = correction, {}, [{'role': 'user', 'content': correction}]
        raw = _extract_raw(model, question, reference_date=reference_date, profile=profile)
    else:
        previous = {k: v for k, v in previous.items() if k in MODELS[model]['inputs']}
        raw = _extract_raw(model, question, reference_date=reference_date, correction=correction, previous=previous, profile=profile)
    return _from_raw(model, raw, previous, question, history, matched)


# --------------------------------------------------------------- formulas
def _value(facts, name, default=None):
    v = facts.get(name, {}).get('value')
    return default if v is None else v


def _months_int(v):
    n = ft.D(v)
    if n != n.to_integral_value() or n < 0:
        raise ValueError('Months must be a whole number')
    return int(n)


def run_formulas(model, target, facts, supporting=()):
    """Apply the selected model's spreadsheet formulas. Returns {result_name: value}."""
    g = lambda n, d=None: _value(facts, n, d)
    if model == 'budget_cash_flow':
        if g('monthly_income') is not None and g('monthly_spending') is not None:
            surplus = ft.D(ft.calculate_cash_flow(monthly_income=g('monthly_income'), monthly_spending=g('monthly_spending'))['monthly_surplus'])
        else:
            surplus = ft.D(g('monthly_surplus'))
        results = {'monthly_surplus': surplus}
        if target != 'monthly_surplus' or set(supporting) & {'projected_surplus', 'affordability_status'}:
            change = ft.D(g('spending_change', 0))
            if g('recurring_cost') is not None:
                new = ft.monthly(g('recurring_cost'), g('recurring_cost_frequency', 'monthly'))
                change += new - ft.monthly(g('replaced_recurring_cost', 0))
                results['spending_change'] = change
            projected = surplus + ft.D(g('income_change', 0)) - change
            results.update(projected_surplus=projected, affordability_status='Yes' if projected >= 0 else 'No')
        return results
    if model == 'savings_goal':
        if g('monthly_contribution') is not None:
            cap = dict(monthly_savings=g('monthly_contribution'))
        elif g('monthly_income') is not None and g('monthly_spending') is not None:
            cap = dict(monthly_income=g('monthly_income'), monthly_spending=g('monthly_spending'))
        else:
            cap = {}
        s = g('available_savings')
        results = {}
        for t in [target, *supporting]:
            if t == 'projected_savings':
                if g('deposit_amount') is not None and g('deposit_count') is not None:
                    r = ft.calculate_savings('future_balance', s, monthly_savings=g('deposit_amount'), months=_months_int(g('deposit_count')))
                else:
                    months = _months_int(g('months'))
                    r = ft.calculate_savings('future_balance', s, months=months, **(cap if months else dict(monthly_savings=0)))
                results['projected_savings'] = ft.D(r['projected_savings'])
            elif t == 'required_monthly_savings':
                r = ft.calculate_savings('monthly_required', s, months=_months_int(g('months')), target=g('goal_amount'))
                results['required_monthly_savings'] = ft.D(r['required_monthly_savings'])
            elif t == 'months_to_goal':
                r = ft.calculate_savings('months_required', s, target=g('goal_amount'), **cap)
                results['months_to_goal'] = r['months_required'] if r['months_required'] is not None else 'Not reachable with that contribution'
            elif t == 'affordability_status':
                months = _months_int(g('months'))
                r = ft.calculate_savings('affordability', s, months=months, target=g('goal_amount'), **(cap if months else dict(monthly_savings=0)))
                results.update(affordability_status='Yes' if r['affordable'] else 'No', projected_savings=ft.D(r['projected_savings']),
                               shortfall=ft.D(r['shortfall']))
        return results
    if model == 'bill_split':
        people = _people(facts)
        if not people:
            raise ValueError('No participants')
        method = g('split_method')
        if method == 'equal':
            r = ft.split_bill('equal', people, total=g('total_bill'))
        elif method == 'itemized':
            items = [dict(amount=i['amount'], shared_by=[str(p) for p in i['shared_by']]) for i in _decoded(g('items'))]
            r = ft.split_bill('itemized', people, items=items, tax=g('tax_amount', 0), tip=g('tip_amount', 0))
        else:
            r = ft.split_custom(g('total_bill'), _decoded(g('split_weights')))
        owed = r['amounts_owed']
        results = {'amounts_owed': owed}
        if 'settlements' in (target, *supporting):
            paid = {str(k): v for k, v in _decoded(g('amounts_paid')).items()}
            total_paid = sum(ft.D(v) for v in paid.values())
            if total_paid == sum(ft.D(v) for v in owed.values()):
                paid = {p: paid.get(p, 0) for p in owed}  # "X paid the whole bill": everyone else paid 0
            s = ft.settle_payments(owed, paid)
            results.update(settlements=s['transfers'], net_balances=s['net_balances'])
        return results
    if model == 'debt_repayment':
        balance, apr = g('principal_balance'), g('apr')
        kwargs = {}
        if target == 'required_monthly_payment' or (g('monthly_payment') is None and g('payoff_months') is not None):
            kwargs['payoff_months'] = _months_int(g('payoff_months'))
        elif g('monthly_payment') is not None:
            kwargs['monthly_payment'] = g('monthly_payment')
        r = ft.calculate_debt_repayment(balance, apr, **kwargs)
        results = {'monthly_interest': ft.D(r['first_month_interest'])}
        if r.get('required_monthly_payment') is not None:
            results['required_monthly_payment'] = ft.D(r['required_monthly_payment'])
        if 'monthly_payment' in kwargs or 'payoff_months' in kwargs:
            if r.get('payoff_possible') is False:
                results.update(estimated_payoff_months='Never: the payment does not cover the monthly interest',
                               total_interest='Not repayable', total_repayment='Not repayable')
            else:
                results['estimated_payoff_months'] = r['payoff_months']
                if r.get('total_interest') is not None:
                    results['total_interest'] = ft.D(r['total_interest'])
                    results['total_repayment'] = ft.D(balance) + ft.D(r['total_interest'])
        return results
    raise ValueError('Unknown model')


# ------------------------------------------------------------- /calculate
LIMITATIONS = {'budget_cash_flow': ['Uses monthly averages; exact payment dates can differ.'],
               'savings_goal': ['Assumes steady contributions and no interest or returns.'],
               'bill_split': ['Cents are reconciled so the shares add up to the bill.'],
               'debt_repayment': ['Assumes a fixed APR charged monthly before each payment, with no fees or new charges.']}

def _show(name, value):
    unit = TARGET_UNITS.get(name)
    value = _decoded(value)
    if isinstance(value, dict):
        return '; '.join(f'{"You" if str(k).lower() == "me" else k}: {_show("_money", v)}' for k, v in value.items())
    if isinstance(value, list):
        if not value:
            return 'Nobody owes anybody.'
        who = lambda p: 'You' if str(p).lower() == 'me' else p
        return '; '.join(f'{who(t["from"])} pay{"" if who(t["from"]) == "You" else "s"} {"you" if str(t["to"]).lower() == "me" else t["to"]} {_show("_money", t["amount"])}' for t in value)
    if isinstance(value, str) and not value.replace('.', '', 1).isdigit():
        return value
    if unit == MONTHS:
        return f'{value} month{"s" if str(value) != "1" else ""}'
    text = '$' + format(ft.D(value).quantize(Decimal('0.01')), ',.2f')
    return text + (' / month' if unit == M else '')


def _m(value):
    """Money for the worked steps: $2,400 or $12.50, with a minus sign for negatives."""
    n = ft.D(value).quantize(Decimal('0.01'))
    text = format(abs(n), ',.2f').removesuffix('.00')
    return ('−$' if n < 0 else '$') + text


def _who(name):
    return 'You' if str(name).lower() == 'me' else str(name)


def _step(label, formula, work, result):
    return dict(label=label, formula=formula, work=work, result=result)


def worked_steps(model, target, facts, results, supporting=()):
    """The formulas actually used, in order, with the user's numbers plugged in."""
    g = lambda n, d=None: _value(facts, n, d)
    targets = [target, *supporting]
    steps = []
    if model == 'budget_cash_flow':
        surplus = results['monthly_surplus']
        if g('monthly_income') is not None and g('monthly_spending') is not None:
            steps.append(_step('Monthly surplus', 'Monthly income − Monthly spending',
                               f'{_m(g("monthly_income"))} − {_m(g("monthly_spending"))}', f'{_m(surplus)}/mo'))
        if 'projected_surplus' in results:
            change = ft.D(g('spending_change', 0))
            if g('recurring_cost') is not None:
                freq = g('recurring_cost_frequency', 'monthly')
                new, old = ft.monthly(g('recurring_cost'), freq), ft.monthly(g('replaced_recurring_cost', 0))
                if freq != 'monthly':
                    steps.append(_step('New cost per month', f'{str(freq).capitalize()} cost converted to a monthly amount',
                                       f'{_m(g("recurring_cost"))} {freq}', f'{_m(new)}/mo'))
                extra = f' + {_m(change)}' if change else ''
                steps.append(_step('Change in monthly spending', 'New cost − Current cost' + (' + Other change' if change else ''),
                                   f'{_m(new)} − {_m(old)}{extra}', f'{_m(results["spending_change"])}/mo'))
                change = results['spending_change']
            projected = results['projected_surplus']
            steps.append(_step('Projected monthly surplus', 'Current surplus + Income change − Spending change',
                               f'{_m(surplus)} + {_m(g("income_change", 0))} − {_m(change)}', f'{_m(projected)}/mo'))
            steps.append(_step('Does it fit?', 'Projected surplus must be at least $0',
                               f'{_m(projected)} {"≥" if projected >= 0 else "<"} $0', results['affordability_status']))
    elif model == 'savings_goal':
        s, goal = g('available_savings', 0), g('goal_amount')
        if g('monthly_contribution') is not None:
            contribution = ft.D(g('monthly_contribution'))
        elif g('monthly_income') is not None and g('monthly_spending') is not None:
            contribution = ft.D(g('monthly_income')) - ft.D(g('monthly_spending'))
            if {'projected_savings', 'months_to_goal', 'affordability_status'} & set(targets) and g('months') != 0:
                steps.append(_step('Monthly contribution', 'Monthly income − Monthly spending',
                                   f'{_m(g("monthly_income"))} − {_m(g("monthly_spending"))}', f'{_m(contribution)}/mo'))
        else:
            contribution = None
        if 'projected_savings' in results:
            proj = results['projected_savings']
            if g('deposit_amount') is not None and g('deposit_count') is not None:
                steps.append(_step('Projected savings', 'Savings + Deposit × Number of deposits',
                                   f'{_m(s)} + {_m(g("deposit_amount"))} × {g("deposit_count")}', _m(proj)))
            elif g('months') == 0:
                steps.append(_step('Money available today', 'Savings (a purchase today has no future contributions)', _m(s), _m(proj)))
            else:
                steps.append(_step('Projected savings', 'Savings + Monthly contribution × Months',
                                   f'{_m(s)} + {_m(contribution)} × {g("months")}', _m(proj)))
        if 'required_monthly_savings' in results:
            steps.append(_step('Required monthly saving', '(Goal − Savings) ÷ Months, rounded up to the cent',
                               f'({_m(goal)} − {_m(s)}) ÷ {g("months")}', f'{_m(results["required_monthly_savings"])}/mo'))
        if 'months_to_goal' in results:
            steps.append(_step('Months to goal', '(Goal − Savings) ÷ Monthly contribution, rounded up',
                               f'({_m(goal)} − {_m(s)}) ÷ {_m(contribution or 0)}', _show('months_to_goal', results['months_to_goal'])))
        if 'affordability_status' in results:
            proj = results['projected_savings']
            ok = results['affordability_status'] == 'Yes'
            steps.append(_step('Can you afford it?', 'Projected savings must be at least the goal',
                               f'{_m(proj)} {"≥" if ok else "<"} {_m(goal)}',
                               f'Yes, with {_m(proj - ft.D(goal))} to spare' if ok else f'No, short by {_m(results["shortfall"])}'))
    elif model == 'bill_split':
        owed = results['amounts_owed']
        method = g('split_method')
        if method == 'equal':
            people = len(owed)
            steps.append(_step('Each person’s share', 'Total bill ÷ Number of people', f'{_m(g("total_bill"))} ÷ {people}',
                               _show('amounts_owed', owed) if len(set(owed.values())) > 1 else f'{_m(next(iter(owed.values())))} each'))
        elif method == 'itemized':
            for item in _decoded(g('items')) or []:
                sharers = [str(p) for p in item.get('shared_by', [])]
                per = ft.D(item['amount']) / max(len(sharers), 1)
                steps.append(_step(str(item.get('name') or 'Item').capitalize(), 'Item price ÷ People who shared it',
                                   f'{_m(item["amount"])} ÷ {len(sharers)} ({", ".join(_who(p) for p in sharers)})',
                                   f'{_m(per)} each' if len(sharers) > 1 else f'{_m(per)} for {_who(sharers[0]) if sharers else "them"}'))
            if ft.D(g('tax_amount', 0)) or ft.D(g('tip_amount', 0)):
                steps.append(_step('Tax and tip', 'Split in proportion to each person’s pretax share',
                                   f'{_m(g("tax_amount", 0))} tax + {_m(g("tip_amount", 0))} tip', 'Added to each share'))
            steps.append(_step('Total per person', 'Sum of each person’s items (plus tax and tip)', '', _show('amounts_owed', owed)))
        else:
            weights = _decoded(g('split_weights')) or {}
            total_w = sum(ft.D(w) for w in weights.values())
            steps.append(_step('Each person’s share', 'Total bill × Weight ÷ Sum of weights',
                               f'{_m(g("total_bill"))} × weight ÷ {total_w.normalize()}', _show('amounts_owed', owed)))
        if 'settlements' in results:
            paid = {str(k): v for k, v in (_decoded(g('amounts_paid')) or {}).items()}
            work = '; '.join(f'{_who(p)}: {_m(paid.get(p, 0))} − {_m(o)}' for p, o in owed.items())
            steps.append(_step('Net balance', 'Amount paid − Amount owed', work,
                               '; '.join(f'{_who(p)}: {_m(v)}' for p, v in results.get('net_balances', {}).items()) or 'Settled'))
            steps.append(_step('Who pays whom', 'People below $0 pay people above $0', '', _show('settlements', results['settlements'])))
    elif model == 'debt_repayment':
        balance, apr = g('principal_balance'), ft.D(g('apr'))
        rate = format((apr / 12).quantize(Decimal('0.0001')).normalize(), 'f')
        steps.append(_step('Monthly interest rate', 'APR ÷ 12', f'{format(apr.normalize(), "f")}% ÷ 12', f'{rate}%'))
        steps.append(_step('First month’s interest', 'Balance × Monthly rate', f'{_m(balance)} × {rate}%', _m(results['monthly_interest'])))
        if 'required_monthly_payment' in results:
            formula = 'Balance ÷ Months (no interest)' if apr == 0 else 'Balance × r ÷ (1 − (1 + r)^−Months), rounded up to the cent'
            steps.append(_step('Required monthly payment', formula,
                               f'{_m(balance)}, {g("payoff_months")} months' + ('' if apr == 0 else f', r = {rate}%'),
                               f'{_m(results["required_monthly_payment"])}/mo'))
        if 'estimated_payoff_months' in results and g('monthly_payment') is not None:
            steps.append(_step('Months to pay off', 'Each month: add that month’s interest, subtract the payment, until the balance is $0',
                               f'{_m(balance)} paying {_m(g("monthly_payment"))}/mo', _show('estimated_payoff_months', results['estimated_payoff_months'])))
        if isinstance(results.get('total_interest'), Decimal):
            steps.append(_step('Total interest', 'Sum of every month’s interest', '', _m(results['total_interest'])))
            steps.append(_step('Total repayment', 'Balance + Total interest', f'{_m(balance)} + {_m(results["total_interest"])}',
                               _m(results['total_repayment'])))
    return steps


def reasoning_assumptions(facts):
    return [dict(variable=f['variable'], value=f['value'], unit=f.get('unit'),
                 how='profile' if 'profile' in str(f.get('source_detail', '')).lower() else f['source'],
                 note=f.get('source_detail') or '') for f in facts.values()]


def _plain(value):
    if isinstance(value, Decimal):
        return float(value.quantize(Decimal('0.01')))
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value


def _facts_from_request(req):
    facts = {a['variable']: dict(a) for a in req.get('assumptions', []) if a.get('value') is not None}
    for name, value in (req.get('extra_inputs') or {}).items():
        facts[name] = dict(variable=name, value=value, unit=None, source='stated', source_detail='Your answer')
    for answer in req.get('answers') or []:
        facts.setdefault(answer['target_variable'], dict(variable=answer['target_variable'], value=answer['answer'],
                                                         unit=None, source='stated', source_detail='Your answer'))
    return facts


def calculate(req):
    meta = req.get('extraction_meta') or {}
    model, target = meta.get('model'), meta.get('target_variable')
    if model not in MODELS or target not in MODELS[model]['targets']:
        reply = free_think(req.get('original_question', ''), req.get('assumptions', []))
        return {'status': 'conditional' if reply['kind'] == 'answer' else 'needs_input',
                'answer': {'headline': reply['text']} if reply['kind'] == 'answer' else None,
                'message': None if reply['kind'] == 'answer' else reply['text'], 'chat_fallback': reply,
                'reasoning': dict(route=route_info('none'), assumptions=[], steps=[], notes=[])}
    supporting = [t for t in meta.get('supporting_targets') or [] if t in MODELS[model]['targets']]
    spec = MODELS[model]
    facts = {k: v for k, v in _facts_from_request(req).items() if k in spec['inputs']}
    for f in facts.values():
        if spec['inputs'][f['variable']][0] is not None:
            f['value'] = _number(f['value'])
    missing = missing_inputs(model, target, facts, supporting)
    if missing:
        return {'status': 'needs_input', 'message': QUESTIONS.get(missing[0], 'A few details are still needed.'),
                'missing_inputs': [dict(variable=n, label=QUESTIONS.get(n), unit=spec['inputs'][n][0],
                                        input_type='number' if spec['inputs'][n][0] else 'text') for n in missing]}
    try:
        results = run_formulas(model, target, facts, supporting)
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        return {'status': 'needs_input', 'message': f'I couldn’t run the {spec["title"]} formulas with these inputs ({exc}). Please check the numbers on the working sheet.'}
    shown = [target, *[t for t in supporting if t in results]]
    if target == 'affordability_status' and 'shortfall' in results:
        # A $0.00 shortfall says nothing; show the projected balance when it is affordable.
        shown.append('shortfall' if results['shortfall'] > 0 else 'projected_savings')
    if target == 'projected_surplus' or target == 'affordability_status':
        shown += [n for n in ('spending_change', 'projected_surplus') if n in results and n not in shown]
    headline = '. '.join(f'{n.replace("_", " ").capitalize()}: {_show(n, results[n])}' for n in shown if n in results)
    factors = [dict(variable=f['variable'], value=f['value'], unit=f.get('unit'), role='known', source=f['source'],
                    source_detail=f.get('source_detail') or 'From your message', relevant=True) for f in facts.values()]
    for name, value in results.items():
        if name in facts or name == 'net_balances':
            continue
        factors.append(dict(variable=name, value=_plain(value), unit=TARGET_UNITS.get(name), role='derived', source='inferred',
                            source_detail=f'Calculated with the {spec["title"]} formulas.', relevant=True))
    response = {'status': 'ready', 'model': model, 'target_variable': target, 'factors': factors,
                'answer': {'headline': headline},
                'explanations': [{'label': spec['title'] + ' formulas', 'text': ' '.join(spec['formulas'])}],
                'limitations': LIMITATIONS[model]}
    try:
        steps = worked_steps(model, target, facts, results, supporting)
    except Exception:  # the steps are a display aid; never lose the answer over them
        steps = []
    response['reasoning'] = dict(route=meta.get('route') or route_info(model), assumptions=reasoning_assumptions(facts),
                                 steps=steps, notes=LIMITATIONS[model])
    try:
        raw = _call_json(EXPLAIN_PROMPT, {'question': req.get('original_question'), 'model': spec['title'],
                                          'inputs': {k: v['value'] for k, v in facts.items()},
                                          'results': {k: _plain(v) for k, v in results.items()}}, 'main_calculation',
                         {'type': 'object', 'properties': {'text': {'type': 'string'}, 'suggestions': {'type': 'array', 'items': {'type': 'string'}}},
                          'required': ['text', 'suggestions']})
        if isinstance(raw.get('text'), str) and raw['text'].strip():
            response['narrative'] = {'text': raw['text'].strip(), 'suggestions': [s for s in raw.get('suggestions') or [] if isinstance(s, str)][:3]}
    except Exception:
        pass  # the explanation is optional; the formula result stands on its own
    return response
