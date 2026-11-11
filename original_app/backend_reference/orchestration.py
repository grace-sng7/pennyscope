"""LLM-first draft, independent verification, Inspector, and reviewed scenarios.

Only a successful review can populate the bounded, short-lived scenario cache.
Financial facts never leave process memory except for the selected Gemini calls.
"""
import hashlib
import inspect
import json
import math
import re
import sys
import threading
import time
from collections import OrderedDict
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from gemini_gateway import call_json
import savings_model

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import dynamic_models
from financial_tools import (calculate_savings, calculate_cash_flow, split_bill,
                             split_custom, settle_payments, calculate_debt_repayment)

TOOLS = {'budget_cash_flow': calculate_cash_flow, 'bill_split': split_bill,
         'bill_custom': split_custom, 'bill_settlement': settle_payments,
         'debt_repayment': calculate_debt_repayment}
CACHE = OrderedDict()
PENDING_REVIEWS = OrderedDict()
LOCK = threading.RLock()
TTL = 1800
MAX_SCENARIOS = 128

MAIN = '''You are Penny Scope's MAIN financial analyst, not a verifier.
Interpret the question and source evidence, choose an existing financial model,
extract its inputs and perform the PRIMARY calculation yourself. Draft a concise
answer and show the calculation with inputs, units and assumptions.
Never invent user facts or treat missing values as zero. Existing savings are not
necessarily available for this goal. If availability is unclear ask for it.
Never treat a recurring cost as a one-time goal. Never assume a partial list of
expenses is the full monthly total. Latest explicit edits win. Unknown means null.
Return JSON:
{"model":"savings_goal" or an available tool name or "gap",
 "target_variable":"the factor being solved", "factors":[{"variable":"...","value":null,"unit":"$","role":"missing","source":"missing","source_detail":"...","relevant":true}],
 "inputs":{}, "bindings":{}, "results":{}, "headline":"...",
 "calculation":"...", "assumptions":["..."],
 "missing_inputs":[{"variable":"...","label":"...","unit":"..."}],
 "gap_reason":"..."}.
Use the existing calculator's exact native keyword arguments and bind every
factual input to its supporting extracted variable. Perform the primary numeric
calculation and return numerical results, not only a symbolic formula. Choose
required inputs according to the selected target; no fixed savings input list.
Do not bind a derived amount as an independently stated input. Never invent a
contribution or savings allocation. For a completed draft, the target factor has
a calculated value, role=derived, source=inferred. Missing inputs are only facts
needed to solve the target, never the target itself.
If a required fact or rule is missing return missing_inputs; no answer yet.
If no supported model fits, return model=gap and explain why. Do not force a model.
'''
INSPECTOR = '''You are the independent Penny Scope Inspector. Review the MAIN
analyst's calculation, Python verification, original question, evidence, units,
source labels, user corrections, and assumptions. Matching arithmetic alone does
not prove correct interpretation. Identify material ambiguities (including savings
availability, partial expenses, recurring versus one-time costs, and estimates).
Classify disagreement as arithmetic, interpretation, missing_evidence, model_gap,
or none. Pure arithmetic errors are resolved using Python's verified numbers;
never ask users to resolve arithmetic. Do not expose internal disagreements.
Return JSON {"decision":"approved"|"needs_input"|"unsupported",
"reason_type":"...", "reason":"brief explanation",
"missing_inputs":[{"variable":"...","label":"...","unit":"..."}],
"assumptions":["important user-visible assumptions; invariant model limitations only, no numeric values or claims about current slider settings"],
"headline":"resolved plain-language answer; for non-savings avoid numeric literals",
"detail":"concise qualitative explanation without numeric literals"}.
Approve only a justified supported model. All material uncertainties require a
question or explicit conditional assumption; never approve fabricated user facts.
'''


MAIN += """
DYNAMIC FACTOR PROTOCOL (overrides the older fixed savings-input rules):
Every existing financial model has shared factors; no factor is permanently an
input or an output. Select model and target_variable from the user's question.
For new requests include target_variable and factors in your draft. Each factor:
{variable, value: number|string|null, unit, role: known|derived|missing,
 source: stated|inferred|missing, source_detail, relevant: true|false}.
Target is separate from role: a target can be missing before solving and derived
in the draft after your primary calculation. Include ONLY relevant factors.
Known factor variable IDs must exactly match their supporting extracted assumption IDs; do not rename them for display.
Known values may come from explicit user statements or Financial Profile evidence;
estimates keep source=inferred even when role=known. Do not relabel estimates as
independently computed. Structured values use JSON-encoded strings.
Python independently verifies your draft values; you perform the primary math.

Use the SAME savings_goal model in all directions. inputs must be native keyword
arguments for calculate_savings: solve_for=future_balance (target projected_savings),
affordability (target affordability_status or shortfall), monthly_required
(target required_monthly_savings or monthly_contribution), months_required (target
months_to_goal or goal_deadline). Native input names: current_savings,
monthly_savings (bind to monthly_contribution), months (bind to goal_deadline),
target (bind to existing goal_amount or target_amount), monthly_income and
monthly_spending (bind to monthly_expenses if that is the existing field).
Never supply both monthly_savings and income/spending. monthly_required does NOT
require income/spending or an existing contribution. months_required does NOT
require a deadline. A projected balance does NOT require a target amount.
Starting savings must be explicit; distinguish holdings from permission to spend.
Do not put a native solver-mode string in bindings; it is your selected method.

Budget uses the existing budget_cash_flow tool. Accept complete category
breakdowns and expense_adjustments=[{name,proposed_reduction}] bound to user facts;
Python will apply these agreed changes independently. No double counting.
Bills use existing bill tools with arbitrary participants/items/weights. Optional
shared_items is another itemized list; optional amounts_paid triggers settlement
verification after allocation. Settlements are a result of the same bill model.
Debt uses existing debt_repayment with balance (bind principal_balance), apr, and
EITHER monthly_payment OR payoff_months. Targets include required_monthly_payment,
estimated_payoff_months, monthly_interest, total_interest, total_repayment.
Use explicit bindings for EVERY native input to the exact extracted fact name.
Do not invent zeros, sharing rules, APR, category reductions or missing factors.
If calculation isn't possible, return relevant factors and missing_inputs for
required unknowns ONLY; never ask the user to supply the target you are solving.
No new sliders, parameters, invented models, React, HTML or layout instructions.
"""
INSPECTOR += """
For drafts with target_variable/factors, verify model selection, target, and
question-specific roles. The SAME factor may be known in one question and solved
in another. Missing inputs must actually be required for this target. Ensure no
target is requested as an input, units match, recurring costs aren't a purchase,
and the primary draft and Python verification use the same evidence/assumptions.
Review the numeric result and roles; final numeric factors come from verification.
"""

def _key(req):
    snapshot = {k: v for k, v in req.items() if k != 'parameters'}
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()


def _facts(req):
    facts = {}
    for a in req['assumptions']:
        k = a['variable']
        if k in facts:
            raise ValueError('Duplicate input variable; please review the extracted facts.')
        if (a['value'] is None) != (a['source'] == 'missing'):
            raise ValueError('An input has inconsistent source labels; please correct it.')
        facts[k] = a
    for k, v in req.get('extra_inputs', {}).items():
        if k not in facts or facts[k]['value'] is None:
            facts[k] = {'value': v, 'unit': None, 'source': 'stated', 'source_detail': 'Entered by user'}
    return facts


def _value(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


def _equal(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except Exception:
        return a == b


def _validate(draft, facts, parameters):
    if draft.get('target_variable') and draft.get('factors') is not None:
        return dynamic_models.validate(draft, facts)
    inputs = draft['inputs']
    bindings = draft.get('bindings', {})
    savings = draft['model'] == 'savings_goal'
    expected_units = {'monthly_income': '$/month', 'monthly_expenses': '$/month',
                      'current_savings': '$', 'goal_amount': '$', 'goal_deadline': 'months'}
    for name, value in inputs.items():
        if not savings and name not in bindings:
            signature = inspect.signature(TOOLS[draft['model']])
            parameter = signature.parameters.get(name)
            if parameter is not None and parameter.default is None and value is None:
                continue
            no_change = draft['model'] == 'budget_cash_flow' and name in ('income_change', 'spending_change')
            included = draft['model'] == 'bill_split' and inputs.get('method') == 'equal' and name in ('tax', 'tip')
            if (no_change or included) and value == 0:
                continue
        if savings and name in ('monthly_contribution', 'use_from_savings'):
            if name in parameters:
                if not _equal(value, parameters[name]):
                    raise ValueError('The draft did not use your current slider settings.')
                continue
            if name == 'monthly_contribution' or (name == 'use_from_savings' and value == 0):
                continue
        source = bindings.get(name, name if savings else None)
        fact = facts.get(source)
        if source == 'monthly_surplus' or not fact or fact['value'] is None:
            raise ValueError('A calculation input needs explicit supporting information.')
        if not _equal(value, _value(fact['value'])):
            raise ValueError('A calculation input differs from the reviewed source value.')
        unit = fact.get('unit')
        generic_units = {'monthly_income': '$/month', 'monthly_spending': '$/month',
                         'monthly_payment': '$/month', 'balance': '$', 'total': '$',
                         'tax': '$', 'tip': '$', 'payoff_months': 'months'}
        expected = expected_units.get(name) if savings else generic_units.get(name)
        if expected and unit not in (None, expected):
            raise ValueError('Please review the units: recurring and one-time amounts cannot be interchanged.')
    if savings:
        required = set(expected_units) | {'monthly_contribution', 'use_from_savings'}
        if set(inputs) != required:
            raise ValueError('The savings draft is incomplete.')
        _verify_savings(inputs)


def _verify_savings(i):
    for k, v in i.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
            raise ValueError('Savings inputs must be finite, nonnegative numbers.')
    if int(i['goal_deadline']) != i['goal_deadline']:
        raise ValueError('Please supply a whole number of months.')
    if i['use_from_savings'] > i['current_savings']:
        raise ValueError('The savings allocation exceeds existing savings.')
    cash = calculate_cash_flow(monthly_income=i['monthly_income'], monthly_spending=i['monthly_expenses'])
    available = Decimal(cash['monthly_surplus'])
    if Decimal(str(i['monthly_contribution'])) > max(Decimal(0), available):
        raise ValueError('The proposed contribution exceeds available monthly cash.')
    r = calculate_savings('affordability', current_savings=i['use_from_savings'],
                         monthly_savings=i['monthly_contribution'], months=int(i['goal_deadline']), target=i['goal_amount'])
    return {'available': float(available), 'projected': float(r['projected_savings']),
            'gap': float(r['shortfall']), 'remaining': float(available - Decimal(str(i['monthly_contribution'])))}


def _verify(draft):
    if draft.get('target_variable') and draft.get('factors') is not None:
        return dynamic_models.verify(draft)
    if draft['model'] == 'savings_goal':
        return _verify_savings(draft['inputs'])
    return TOOLS[draft['model']](**draft['inputs'])


def _disagreements(proposed, actual, path=''):
    differences = []
    for key, value in actual.items():
        p = f'{path}.{key}' if path else key
        other = proposed.get(key) if isinstance(proposed, dict) else None
        if isinstance(value, dict):
            differences.extend(_disagreements(other, value, p))
        elif isinstance(value, (int, float)) or (isinstance(value, str) and value.replace('.', '', 1).lstrip('-').isdigit()):
            try:
                if other is None or abs(Decimal(str(other)) - Decimal(str(value))) > Decimal('0.005'):
                    differences.append(p)
            except Exception:
                differences.append(p)
        elif other != value:
            differences.append(p)
    return differences


def _present(draft, actual, review, req):
    if draft.get('target_variable') and draft.get('factors') is not None:
        return dynamic_models.present(draft, actual, review, _facts(req))
    if draft['model'] == 'savings_goal':
        # Reuse the original UI formatter, passing the resolved plan and verified
        # arithmetic. It no longer invents the primary plan or initial answer.
        result = savings_model.present_verified(draft['inputs'], actual, review)
        result['parameters'][1]['max'] = draft.get('savings_limit', draft['inputs']['use_from_savings'])
        return result
    def rows(data, prefix=''):
        output = []
        for key, value in data.items():
            if value is None or key in ('model', 'method'):
                continue
            label = (prefix + ' ' + key.replace('_', ' ')).strip().capitalize()
            if isinstance(value, dict):
                output.extend(rows(value, label))
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, dict) and {'from', 'to', 'amount'} <= set(item):
                        output.append({'label': f"{item['from']} pays {item['to']}", 'value': '$' + str(item['amount'])})
            else:
                output.append({'label': label, 'value': str(value)})
        return output
    formulas = {
        'budget_cash_flow': 'Monthly surplus = monthly income − monthly spending. Scenario changes are applied only when explicitly supplied.',
        'bill_split': 'Allocate the agreed bill by the reviewed sharing rule; reconcile rounding to the cent.',
        'bill_custom': 'Each share = total × agreed weight ÷ total weights; reconcile rounding to the cent.',
        'bill_settlement': 'Net balance = amount paid − amount owed; transfers reconcile all balances.',
        'debt_repayment': 'Monthly interest = outstanding balance × APR ÷ 1200. Apply the monthly payment and repeat until paid off.',
    }
    return {'status': 'conditional', 'answer': {'headline': review['headline'], 'detail': review.get('detail', '')},
            'metrics': rows(actual),
            'explanations': [{'label': 'Verified calculation', 'text': formulas[draft['model']]}],
            'assumptions': [{'text': s} for s in review.get('assumptions', [])],
            'limitations': ['Results use the reviewed inputs and model assumptions.']}



def calculate(req):
    try:
        facts = _facts(req)
        key = _key(req)
        parameters = req.get('parameters', {})
        with LOCK:
            cached = CACHE.get(key)
            if cached and time.monotonic() - cached['time'] > TTL:
                del CACHE[key]
                cached = None
        if cached:
            draft = json.loads(json.dumps(cached['draft']))
            if parameters and draft.get('target_variable'):
                raise ValueError('This reviewed result has no scenario controls.')
            if parameters:
                if draft['model'] != 'savings_goal' or set(parameters) - {'monthly_contribution', 'use_from_savings'}:
                    raise ValueError('These controls are not part of the reviewed scenario.')
                for k, v in parameters.items():
                    draft['inputs'][k] = v
                if draft['inputs']['use_from_savings'] > cached['savings_limit']:
                    raise ValueError('This allocation exceeds the reviewed savings permission.')
            actual = _verify(draft)
            review = dict(cached['review'])
            review['detail'] = 'Based on the reviewed model and your current scenario settings.'
            return _present(draft, actual, review, req)
        # Unknown parameter controls may not create an unchecked financial scenario.
        if set(parameters) - {'monthly_contribution', 'use_from_savings'}:
            raise ValueError('Unknown scenario control; please review the question again.')
        pending_key = hashlib.sha256(json.dumps(req, sort_keys=True).encode()).hexdigest()
        with LOCK:
            pending = PENDING_REVIEWS.get(pending_key)
            if pending and time.monotonic() - pending['time'] > TTL:
                del PENDING_REVIEWS[pending_key]
                pending = None
        if pending:
            # Retry resumes only the failed Inspector; facts and draft stay fixed.
            draft, actual, differences = pending['draft'], pending['actual'], pending['differences']
        else:
            schemas = {k: {'signature': str(inspect.signature(v)), 'description': inspect.getdoc(v)} for k, v in dynamic_models.TOOLS.items()}
            draft = call_json(MAIN, json.dumps({'request': req, 'available_tools': schemas}, default=str), stage='main_calculation')
            if draft.get('missing_inputs'):
                return {'status': 'needs_input', 'message': 'Please clarify these details before a result can be reviewed.', 'missing_inputs': draft['missing_inputs']}
            if draft.get('model') not in {'savings_goal', *TOOLS}:
                return {'status': 'unsupported', 'message': draft.get('gap_reason') or 'No existing financial model fits this question.'}
            _validate(draft, facts, parameters)
            actual = _verify(draft)
            differences = _disagreements(draft.get('results', {}), actual)
            with LOCK:
                PENDING_REVIEWS[pending_key] = {'time': time.monotonic(), 'draft': draft, 'actual': actual, 'differences': differences}
                PENDING_REVIEWS.move_to_end(pending_key)
                while len(PENDING_REVIEWS) > MAX_SCENARIOS:
                    PENDING_REVIEWS.popitem(last=False)
        review = call_json(INSPECTOR, json.dumps({'request': req, 'main_draft': draft,
                          'python_result': actual, 'arithmetic_disagreements': differences}, default=str), stage='inspector')
        with LOCK:
            PENDING_REVIEWS.pop(pending_key, None)
        if review.get('decision') == 'needs_input':
            if not review.get('missing_inputs'):
                raise ValueError('The review needs more information; please clarify the question.')
            return {'status': 'needs_input', 'message': 'Please clarify these details before a final answer.', 'missing_inputs': review['missing_inputs']}
        if review.get('decision') == 'unsupported':
            return {'status': 'unsupported', 'message': review.get('reason', 'This scenario needs another financial model.')}
        if review.get('decision') != 'approved' or not isinstance(review.get('headline'), str) or not isinstance(review.get('assumptions'), list):
            raise ValueError('The independent review was incomplete; please retry.')
        if draft['model'] != 'savings_goal' and re.search(r'\d', review['headline'] + review.get('detail', '')):
            if draft.get('target_variable') and draft.get('factors') is not None:
                # Factor-aware headlines are rebuilt from verified values. An
                # unused Inspector headline mentioning the charge isn't a failure.
                # Keep unverified numeric prose out of the displayed detail.
                review = dict(review)
                if re.search(r'\d', review.get('detail', '')):
                    review['detail'] = 'Based on the reviewed inputs and assumptions shown here.'
            else:
                raise ValueError('Numeric claims must be shown only in independently verified metrics.')
        savings_limit = draft['inputs'].get('use_from_savings', 0)
        if draft['model'] == 'savings_goal' and not draft.get('target_variable'):
            fact = facts.get('available_savings')
            if fact and fact['source'] == 'stated' and isinstance(fact['value'], (int, float)):
                savings_limit = min(draft['inputs']['current_savings'], fact['value'])
        draft['savings_limit'] = savings_limit
        result = _present(draft, actual, review, req)
        from contract import CalculateResponse
        CalculateResponse.model_validate(result)
        with LOCK:
            CACHE[key] = {'time': time.monotonic(), 'draft': draft, 'review': review, 'savings_limit': savings_limit}
            CACHE.move_to_end(key)
            while len(CACHE) > MAX_SCENARIOS:
                CACHE.popitem(last=False)
        return result
    except (ValueError, TypeError, KeyError, ArithmeticError):
        # Never reveal provider content, draft internals, or invalid financial values.
        raise HTTPException(status_code=422, detail='The calculation could not be verified against your inputs. Please review amounts, units and missing information, then retry.') from None


MAIN += """
Worked reverse-savings example (use the actual user's values, not these values):
If starting savings=200, goal_amount=1200, goal_deadline=5 months, and the user asks
what to save monthly, select model=savings_goal, target_variable=required_monthly_savings.
Use inputs={"solve_for":"monthly_required","current_savings":200,"target":1200,"months":5}
and bindings={"current_savings":"current_savings","target":"goal_amount","months":"goal_deadline"}.
Your primary calculation is (1200-200)/5=200, so results includes
{"required_monthly_savings":200}. Include the target factor with value=200,
unit="$/month", role="derived", source="inferred". Do NOT leave it null or missing.
Include known factors with their exact supporting extracted variable names.
"""


MAIN += """
Recurring expenses are budget_cash_flow, not savings_goal: frequency words
monthly/weekly/every two weeks/yearly and ongoing rent/utilities/memberships signal
recurrence. One-time deposits and fees remain distinct. Model selection stays
semantic; do not route bill settlement or loan payoff to budget just because an
amount is monthly. For a new recurring expense, solve projected_surplus or
budget affordability_status; no savings balance or goal deadline is required.
Use native inputs income_entries or monthly_income (not both), spending_entries
or monthly_spending (not both), and spending_change for an explicit monthly new
charge. Bind spending_change to recurring_cost or its exact extracted name.
For weekly/biweekly/yearly new charges use spending_change_entries, bound to the
raw periodic entries; Python normalizes the same periodic amount independently.
A positive spending_change increases spending; a reduction is negative.
Prefer raw periodic income_entries over an LLM-derived monthly_income when raw
frequency evidence exists. Every two weeks=26/year, twice monthly=24/year,
weekly=52/year. Explain monthly averaging; pay-date cash timing is not modeled.
Example: income_entries=[{"amount":900,"frequency":"biweekly","category":"fixed"}],
monthly_spending=1650, spending_change=90 -> monthly_income=1950,
monthly_surplus=300, scenario_monthly_surplus=210, affordable=true.
For this example return the target projected_surplus=210 derived, and the income
and before/after surplus as derived factors. Never invent a savings goal.
"""
INSPECTOR += """
For recurring charges verify budget model choice, explicit frequency, correct
weekly/biweekly/semimonthly annualization, and whether new spending is additional
rather than already included. Savings and a goal deadline are not necessary for
ongoing budget-fit questions. A positive average surplus is a budget fit under
the stated assumptions, not a guarantee of cash available on each payment date.
"""
