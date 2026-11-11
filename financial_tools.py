"""Penny Scope V1: deterministic financial models (no LLM arithmetic).

All amounts are in one currency, supplied by the caller. Money is rounded to
cents at output. The model deliberately does NOT infer missing user finances.

MODEL LIBRARY
1. budget_cash_flow: M = income - spending; change M by monthly deltas.
2. savings_projection: F = S + M*N; solve for F, M, N or yes/no target.
3. bill_splitting: allocate bill equally or by items; settle who pays whom.
4. debt_repayment: monthly interest B*(APR/100)/12; amortize monthly.

Assumptions: monthly-average cash flow, no daily liquidity projections;
savings have no interest/returns; debt APR is constant and interest accrues
once per month, with payments after interest. Real card statements differ.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from typing import Any

CENT = Decimal("0.01")
PER_YEAR = {"weekly": Decimal(52), "biweekly": Decimal(26),
            "semimonthly": Decimal(24), "monthly": Decimal(12),
            "quarterly": Decimal(4), "annually": Decimal(1)}


def D(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a financial amount")
    try:
        v = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"Invalid number: {value}") from exc
    if not v.is_finite():
        raise ValueError("Amount must be finite")
    return v


def money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def nonnegative(value: Any, name: str) -> Decimal:
    v = D(value)
    if v < 0:
        raise ValueError(f"{name} cannot be negative")
    return v


def monthly(amount: Any, frequency: str = "monthly") -> Decimal:
    """Monthly equivalent: amount * occurrences_per_year / 12."""
    if frequency not in PER_YEAR:
        raise ValueError(f"Unknown frequency: {frequency}")
    return nonnegative(amount, "amount") * PER_YEAR[frequency] / 12


def _monthly_entries(entries: list[dict] | None) -> Decimal:
    return sum((monthly(e["amount"], e.get("frequency", "monthly"))
                for e in (entries or [])), Decimal(0))


# ---------------------- MODEL 1: BUDGET & CASH FLOW ----------------------
def calculate_cash_flow(
    monthly_income: Any | None = None,
    monthly_spending: Any | None = None,
    income_entries: list[dict] | None = None,
    spending_entries: list[dict] | None = None,
    income_change: Any = 0,
    spending_change: Any = 0,
    *,
    fixed_income: Any | None = None,
    variable_income: Any | None = None,
    fixed_costs: Any | None = None,
    variable_costs: Any | None = None,
    expense_categories: list[dict] | None = None,
) -> dict:
    """Monthly cash flow and possible expense reductions.

    Income source: (monthly_income), (income_entries), OR
      (fixed_income + variable_income).
    Spending source: (monthly_spending), (spending_entries), OR
      (fixed_costs + variable_costs). Zero must be supplied explicitly if known.
    Detailed entries have amount, optional frequency, and category fixed/variable.
    expense_categories (optional, must not be added to spending again):
      [{'name':'entertainment','amount':500,'frequency':'monthly',
        'flexibility':'discretionary','proposed_reduction':100}]
    Category totals must match spending amount if provided as a complete breakdown.
    proposed_reduction is a USER-specified scenario, never an automatic recommendation.
    """
    income_options = [monthly_income is not None, income_entries is not None,
                      fixed_income is not None or variable_income is not None]
    spending_options = [monthly_spending is not None, spending_entries is not None,
                        fixed_costs is not None or variable_costs is not None]
    if sum(income_options) != 1 or sum(spending_options) != 1:
        raise ValueError("Choose exactly one income source and one spending source")

    def classify(entries, field):
        fixed = variable = Decimal(0)
        for entry in entries:
            category = entry.get('category')
            if category not in ('fixed', 'variable'):
                raise ValueError(f"{field} entries require category fixed or variable")
            v = monthly(entry['amount'], entry.get('frequency','monthly'))
            if category == 'fixed': fixed += v
            else: variable += v
        return fixed, variable

    inc_fixed = inc_variable = exp_fixed = exp_variable = None
    if monthly_income is not None: inc = nonnegative(monthly_income, 'monthly_income')
    elif income_entries is not None:
        inc_fixed, inc_variable = classify(income_entries, 'income')
        inc = inc_fixed + inc_variable
    else:
        inc_fixed = nonnegative(0 if fixed_income is None else fixed_income, 'fixed_income')
        inc_variable = nonnegative(0 if variable_income is None else variable_income, 'variable_income')
        inc = inc_fixed + inc_variable
    if monthly_spending is not None: exp = nonnegative(monthly_spending, 'monthly_spending')
    elif spending_entries is not None:
        exp_fixed, exp_variable = classify(spending_entries, 'spending')
        exp = exp_fixed + exp_variable
    else:
        exp_fixed = nonnegative(0 if fixed_costs is None else fixed_costs, 'fixed_costs')
        exp_variable = nonnegative(0 if variable_costs is None else variable_costs, 'variable_costs')
        exp = exp_fixed + exp_variable

    delta_inc, delta_exp = D(income_change), D(spending_change)
    if inc + delta_inc < 0 or exp + delta_exp < 0:
        raise ValueError('Scenario income/spending cannot be negative')
    surplus = inc - exp
    result = {'model':'budget_cash_flow', 'monthly_income':money(inc),
              'monthly_spending':money(exp), 'monthly_surplus':money(surplus),
              'scenario_monthly_surplus':money(surplus+delta_inc-delta_exp),
              'monthly_surplus_change':money(delta_inc-delta_exp)}
    for name, v in [('fixed_income',inc_fixed),('variable_income',inc_variable),
                    ('fixed_costs',exp_fixed),('variable_costs',exp_variable)]:
        result[name] = money(v) if v is not None else None
    if inc_fixed is not None:
        result['surplus_excluding_variable_income'] = money(inc_fixed-exp)
    if expense_categories is not None:
        categories=[]
        total=Decimal(0); total_reduction=Decimal(0)
        for e in expense_categories:
            name=e.get('name')
            flex=e.get('flexibility')
            if not isinstance(name,str) or not name.strip():
                raise ValueError('Expense category requires name')
            if flex not in ('essential','adjustable','discretionary'):
                raise ValueError('Expense category requires flexibility')
            amt=monthly(e['amount'],e.get('frequency','monthly'))
            reduction=nonnegative(e.get('proposed_reduction',0),'proposed_reduction')
            if reduction>amt: raise ValueError('Proposed reduction exceeds category spending')
            total+=amt; total_reduction+=reduction
            categories.append({'name':name,'flexibility':flex,'monthly_amount':money(amt),
                               'proposed_reduction':money(reduction)})
        if abs(total-exp)>Decimal('0.01'):
            raise ValueError('Expense category breakdown must sum to monthly spending')
        if total_reduction>0 and delta_exp != 0:
            raise ValueError('Use proposed category reductions OR spending_change, not both')
        result['expense_categories']=categories
        result['potential_user_selected_reduction']=money(total_reduction)
        if total_reduction:
            result['scenario_monthly_surplus']=money(surplus+delta_inc+total_reduction)
            result['monthly_surplus_change']=money(delta_inc+total_reduction)
        result['spending_by_flexibility']={f:money(sum((D(x['monthly_amount']) for x in categories if x['flexibility']==f),Decimal(0)))
                                          for f in ('essential','adjustable','discretionary')}
    return result


# ------------------- MODEL 2: SAVINGS / AFFORDABILITY --------------------
def calculate_savings(
    solve_for: str,
    current_savings: Any = 0,
    monthly_savings: Any | None = None,
    months: int | None = None,
    target: Any | None = None,
    monthly_income: Any | None = None,
    monthly_spending: Any | None = None,
) -> dict:
    """Same relationship for purchases AND savings goals: F = S + M*N.

    solve_for choices:
      'future_balance': requires M and N
      'affordability': requires M, N and target; returns yes/no
      'monthly_required': requires N > 0 and target
      'months_required': requires M > 0 and target

    M may be supplied directly OR derived from monthly_income - monthly_spending.
    S is money explicitly available for THIS goal, not a full bank balance.
    No future contribution is included if months=0 (purchase today).
    """
    allowed = {"future_balance", "affordability", "monthly_required", "months_required"}
    if solve_for not in allowed:
        raise ValueError(f"solve_for must be one of {sorted(allowed)}")
    s = nonnegative(current_savings, "current_savings")
    if monthly_savings is not None and (monthly_income is not None or monthly_spending is not None):
        raise ValueError("Provide monthly_savings OR income and spending, not both")
    if monthly_savings is None and monthly_income is not None and monthly_spending is not None:
        m = nonnegative(monthly_income, "monthly_income") - nonnegative(monthly_spending, "monthly_spending")
    elif monthly_savings is not None:
        m = D(monthly_savings)
    else:
        m = None
    if months is not None and (isinstance(months, bool) or not isinstance(months, int) or months < 0):
        raise ValueError("months must be a nonnegative integer")
    t = None if target is None else nonnegative(target, "target")
    result: dict[str, Any] = {"model": "savings_projection", "solve_for": solve_for,
                              "current_savings": money(s)}
    if solve_for in ("future_balance", "affordability"):
        if m is None or months is None:
            raise ValueError("monthly savings and months required")
        f = s + m * months
        result.update(projected_savings=money(f), monthly_savings=money(m), months=months)
        if solve_for == "affordability":
            if t is None:
                raise ValueError("target required")
            result.update(target=money(t), affordable=f >= t,
                          remaining_after_goal=money(f - t),
                          shortfall=money(max(Decimal(0), t - f)),
                          offer_budgeting=f < t)
    elif solve_for == "monthly_required":
        if t is None or months is None:
            raise ValueError("target and months required")
        shortfall = max(Decimal(0), t - s)
        if months == 0 and shortfall > 0:
            raise ValueError("Cannot accumulate missing savings in zero months")
        required = (shortfall / months if months else Decimal(0))
        # Round required payment UP to the cent so it really reaches the goal.
        required = required.quantize(CENT, rounding=ROUND_CEILING)
        result.update(target=money(t), months=months, required_monthly_savings=money(required))
        if m is not None:
            result.update(monthly_capacity=money(m), feasible=m >= required,
                          offer_budgeting=m < required)
    else:  # months_required
        if t is None or m is None:
            raise ValueError("target and monthly savings required")
        needed = max(Decimal(0), t - s)
        if needed > 0 and m <= 0:
            result.update(target=money(t), months_required=None,
                          feasible=False, offer_budgeting=True)
        else:
            n = int((needed / m).to_integral_value(rounding=ROUND_CEILING)) if needed else 0
            result.update(target=money(t), months_required=n, feasible=True)
    return result


# -------------------------- MODEL 3: BILL SPLITTING ---------------------
def _cents(amount: Any) -> int:
    v = nonnegative(amount, "amount")
    if v != v.quantize(CENT):
        raise ValueError("Bill amounts must have at most two decimals")
    return int(v * 100)


def _allocate(total_cents: int, weights: list[int]) -> list[int]:
    if not weights or any(w < 0 for w in weights) or sum(weights) <= 0:
        raise ValueError("Weights must be nonnegative and sum above zero")
    denom = sum(weights)
    base = [total_cents * w // denom for w in weights]
    remainder = total_cents - sum(base)
    order = sorted(range(len(weights)), key=lambda i: (-(total_cents * weights[i] % denom), i))
    for i in order[:remainder]:
        base[i] += 1
    return base


def _from_cents(c: int) -> str:
    return money(Decimal(c) / 100)


def split_bill(
    method: str,
    people: list[str],
    total: Any | None = None,
    items: list[dict] | None = None,
    tax: Any = 0,
    tip: Any = 0,
) -> dict:
    """Optional deterministic arithmetic for LLM-defined splits.

    The LLM must first clarify what counts as shared, who participated,
    how tax/tip is allocated, and what was already paid.
    This function handles only equal and specific itemized splits; for
    custom rules the agent should ask clarification and propose an agreed
    explicit allocation, not silently force a method.

    Split methods: 'equal' or 'itemized'.

    equal: total required, divided equally; tax/tip assumed INCLUDED in total.
    itemized: items=[{'amount': 30, 'shared_by': ['A']},
                     {'amount': 12, 'shared_by': ['A','B']}].
      Total = sum(items) + tax + tip, with tax/tip allocated proportional
      to pre-tax individual shares. Shared items split equally between named diners.
      If total is supplied in itemized mode, it must equal computed total.
    """
    if not people or len(set(people)) != len(people) or any(not p for p in people):
        raise ValueError("Provide distinct nonempty people")
    if method == "equal":
        if total is None:
            raise ValueError("total is required")
        if _cents(tax) or _cents(tip) or items is not None:
            raise ValueError("Equal split total already includes tax/tip; no items")
        owed = _allocate(_cents(total), [1] * len(people))
        bill = _cents(total)
    elif method == "itemized":
        if not items:
            raise ValueError("items required")
        subtotal = [0] * len(people)
        for item in items:
            recipients = item.get("shared_by", [])
            if not recipients or len(set(recipients)) != len(recipients) or any(p not in people for p in recipients):
                raise ValueError("Every item needs valid, unique shared_by diners")
            shares = _allocate(_cents(item["amount"]), [1] * len(recipients))
            for p, cents in zip(recipients, shares):
                subtotal[people.index(p)] += cents
        bill = sum(subtotal) + _cents(tax) + _cents(tip)
        if total is not None and _cents(total) != bill:
            raise ValueError("Provided total differs from itemized subtotal + tax + tip")
        charges = _allocate(_cents(tax) + _cents(tip), subtotal) if sum(subtotal) else _allocate(_cents(tax) + _cents(tip), [1]*len(people))
        owed = [a+b for a,b in zip(subtotal, charges)]
    else:
        raise ValueError("method must be 'equal' or 'itemized'")
    return {"model": "bill_splitting", "method": method, "total": _from_cents(bill),
            "amounts_owed": {p: _from_cents(v) for p,v in zip(people,owed)}}


def split_custom(total: Any, weights: dict[str, Any]) -> dict:
    """Flexible user-approved ratio allocation for unusual bill scenarios.

    Agent clarifies exact people and allocation rules first, then converts
    those instructions into nonnegative weights. No silent assumption about
    shared meals, tax, tip, or who consumed what.
    Example: weights={'A':2, 'B':1, 'C':1} gives a 50/25/25 split.
    """
    if not weights or any(not isinstance(k,str) or not k.strip() for k in weights):
        raise ValueError('Provide nonempty person names')
    names=list(weights)
    raw=[nonnegative(v,'weight') for v in weights.values()]
    if sum(raw)==0: raise ValueError('At least one positive weight required')
    # Decimal scaling retains exact decimal ratios without float conversions.
    places=max(0,*(max(0,-v.as_tuple().exponent) for v in raw))
    factors=[int(v * (Decimal(10)**places)) for v in raw]
    shares=_allocate(_cents(total),factors)
    return {'model':'bill_splitting','method':'custom_weights',
            'total':_from_cents(_cents(total)),
            'amounts_owed':{name:_from_cents(share) for name,share in zip(names,shares)}}


def settle_payments(amounts_owed: dict[str, Any], amounts_paid: dict[str, Any]) -> dict:
    """Net = paid - owed. Debtors transfer to creditors; no external payments.

    Requires paid and owed amounts to refer to the SAME total bill.
    Transfer set is valid but not guaranteed globally minimum in transaction count.
    """
    if not amounts_owed or set(amounts_owed) != set(amounts_paid):
        raise ValueError("Owed and paid must have identical person keys")
    people = list(amounts_owed)
    owed = [_cents(amounts_owed[p]) for p in people]
    paid = [_cents(amounts_paid[p]) for p in people]
    if sum(owed) != sum(paid):
        raise ValueError("Total already paid must equal total owed")
    debtors = [[people[i], owed[i]-paid[i]] for i in range(len(people)) if owed[i]>paid[i]]
    creditors = [[people[i], paid[i]-owed[i]] for i in range(len(people)) if paid[i]>owed[i]]
    transfers=[]
    a=b=0
    while a<len(debtors) and b<len(creditors):
        amt=min(debtors[a][1], creditors[b][1])
        transfers.append({"from": debtors[a][0], "to": creditors[b][0], "amount": _from_cents(amt)})
        debtors[a][1]-=amt
        creditors[b][1]-=amt
        if debtors[a][1]==0: a+=1
        if creditors[b][1]==0: b+=1
    return {"model": "bill_splitting", "transfers": transfers,
            "net_balances": {p: _from_cents(paid[i]-owed[i]) for i,p in enumerate(people)}}


# ------------------------- MODEL 4: BASIC DEBT --------------------------
def calculate_debt_repayment(
    balance: Any,
    apr: Any,
    monthly_payment: Any | None = None,
    payoff_months: int | None = None,
) -> dict:
    """Simplified fixed APR monthly amortization, no fees or new charges.

    r = APR/100/12; first_month_interest = B*r; B_next = B*(1+r)-P.
    Provide EITHER monthly_payment (calculate payoff) OR payoff_months
    (calculate required payment), or neither (first month interest only).
    Credit card actual interest may use daily balances and grace periods.
    """
    b = nonnegative(balance, "balance")
    a = nonnegative(apr, "apr")
    r = a / 1200
    if monthly_payment is not None and payoff_months is not None:
        raise ValueError("Provide monthly_payment OR payoff_months")
    result: dict[str, Any] = {"model": "debt_repayment", "balance": money(b),
                              "apr_percent": str(a), "first_month_interest": money(b*r)}
    if payoff_months is not None:
        if isinstance(payoff_months, bool) or not isinstance(payoff_months, int) or payoff_months <= 0:
            raise ValueError("payoff_months must be a positive integer")
        if b == 0:
            p = Decimal(0)
        elif r == 0:
            p = b / payoff_months
        else:
            p = b*r / (1-(1+r)**(-payoff_months))
        # Ceiling to cents prevents a remaining unpaid few cents.
        p = p.quantize(CENT, rounding=ROUND_CEILING)
        result.update(payoff_months=payoff_months, required_monthly_payment=money(p))
        monthly_payment = p
    if monthly_payment is not None:
        p = nonnegative(monthly_payment, "monthly_payment")
        if b > 0 and (p <= b*r):
            result.update(payoff_possible=False, payoff_months=None, total_interest=None)
            return result
        remaining=b
        total_interest=Decimal(0)
        count=0
        while remaining > 0 and count < 1200:
            interest=remaining*r
            total_interest+=interest
            remaining=max(Decimal(0), remaining+interest-p)
            count+=1
            if remaining < CENT / 100:
                remaining=Decimal(0)
        result.update(payoff_possible=remaining==0,
                      payoff_months=count if remaining==0 else None,
                      total_interest=money(total_interest) if remaining==0 else None,
                      monthly_payment=money(p))
    return result


def compare_debt_payments(balance: Any, apr: Any,
                          monthly_payments: list[Any] | None = None,
                          payoff_months_options: list[int] | None = None) -> dict:
    """Compare paying different monthly amounts OR payoff time horizons.

    Returns monthly payment, payoff months, total interest and total paid
    for each scenario, using the same simplified monthly amortization model.
    These are alternatives (not extra obligations added together).
    """
    if (monthly_payments is None) == (payoff_months_options is None):
        raise ValueError('Provide exactly one scenario list')
    options = monthly_payments if monthly_payments is not None else payoff_months_options
    if not options:
        raise ValueError('Provide at least one scenario')
    scenarios=[]
    for option in options:
        if monthly_payments is not None:
            result=calculate_debt_repayment(balance,apr,monthly_payment=option)
            label={'requested_monthly_payment':money(nonnegative(option,'monthly_payment'))}
        else:
            result=calculate_debt_repayment(balance,apr,payoff_months=option)
            label={'requested_payoff_months':option}
        total_interest=result['total_interest']
        scenarios.append({**label,'monthly_payment':result.get('monthly_payment'),
                          'payoff_months':result['payoff_months'],
                          'payoff_possible':result.get('payoff_possible',True),
                          'total_interest':total_interest,
                          'total_repayment':money(D(balance)+D(total_interest)) if total_interest is not None else None})
    return {'model':'debt_repayment','balance':money(nonnegative(balance,'balance')),
            'apr_percent':str(nonnegative(apr,'apr')),'scenarios':scenarios}


# Registry descriptions can be supplied to an LLM (not used as calculator inputs).
MODEL_REGISTRY = {
    "budget_cash_flow": {
        "tool": "calculate_cash_flow",
        "use_when": "User wants fixed/variable income and expense breakdown, surplus, expense savings opportunities, or recurring cost scenarios",
        "do_not_use_when": "User only asks bill sharing or interest on debt",
        "formula": "monthly_surplus=income-spending; scenario_surplus=surplus+delta_income-delta_spending",
    },
    "savings_projection": {
        "tool": "calculate_savings",
        "use_when": "User asks can I afford a purchase by date, reach savings goal, required monthly saving or months to goal",
        "do_not_use_when": "User asks who owes whom for shared spending",
        "formula": "future_savings=current_savings+monthly_savings*months; use solve_for to rearrange",
    },
    "bill_splitting": {
        "tool": "split_bill / split_custom / settle_payments",
        "use_when": "User shares bills under custom rules; LLM clarifies participants, item ownership, taxes, tips, and payer settlement before calculation",
        "do_not_use_when": "User asks if personal purchase fits their own budget",
        "formula": "owed=sum(allocated_items)+allocated_tax_tip; net=paid-owed",
    },
    "debt_repayment": {
        "tool": "calculate_debt_repayment / compare_debt_payments",
        "use_when": "User asks required monthly repayment, payoff time at different payments, or total interest across longer versus shorter repayment plans",
        "do_not_use_when": "User asks about a purchase with no borrowed balance or APR",
        "formula": "monthly_rate=APR/1200; interest=balance*rate; next_balance=balance+interest-payment",
    },
}
