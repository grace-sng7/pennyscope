# Penny Scope Financial Models V2: Formula and Interaction Review

**Status:** Standalone Python calculators with validation and tests. Not yet integrated with smolagents, the team's financial profile, or the frontend.

## Model 1. Budget & Cash Flow

**Purpose:** Identify how much a user has left monthly and explore *where spending could be reduced*, without requiring a detailed expense breakdown for every question.

### Inputs

| Variable | Meaning |
|---|---|
| `fixed_income` | Predictable monthly income |
| `variable_income` | Estimated irregular monthly income (not guaranteed) |
| `fixed_costs` | Regular relatively stable monthly expenses |
| `variable_costs` | Monthly expenses that vary |
| `expense_categories` | Optional itemized expenses, tagged `essential`, `adjustable`, or `discretionary`; user may specify `proposed_reduction` |

Instead of the four buckets, a financial profile can supply aggregate `monthly_income`, `monthly_spending`, or itemized `income_entries` and `spending_entries`, with frequencies normalized to monthly. Choose **one** source per side to avoid double counting. Itemized entries must include `category: fixed` or `variable`. Expense category totals must cover the same spending amount if supplied.

### Calculation

`monthly_income = fixed_income + variable_income`

`monthly_spending = fixed_costs + variable_costs`

`monthly_surplus = monthly_income - monthly_spending`

`surplus_excluding_variable_income = fixed_income - monthly_spending` (only when buckets are known)

`new_surplus = monthly_surplus + income_change - spending_change`

For a user-selected budget-cut scenario:

`new_surplus = monthly_surplus + income_change + sum(proposed_reductions)`

**Outputs:** Monthly income, total expenses, fixed/variable components when known, monthly surplus, optional expense breakdown by flexibility, and before/after surplus. **Do not automatically assume a discretionary expense can be entirely eliminated.** User chooses potential reductions. No daily liquidity or credit-card timing calculations.

## Model 2. Savings Projection / One-Time Purchase

**Purpose:** The same calculation model supports a one-time purchase and a saving goal. This model normally answers Yes/No plus a number, then optionally offers budgeting for No.

**Inputs:** `current_savings` available for the goal, `months`, `target`, and either `monthly_savings` or both `monthly_income` and `monthly_spending`.

**Derived monthly savings:** `M = monthly_income - monthly_spending`, if monthly savings isn't directly known.

**Core formula:** `future_savings = current_savings + M * months`.

| `solve_for` | Calculation |
|---|---|
| `future_balance` | `S + M*N` |
| `affordability` | Yes when `S + M*N >= target`; return remaining/shortfall |
| `monthly_required` | `ceil_to_cent(max(0,target-S)/N)` |
| `months_required` | `ceil(max(0,target-S)/M)` if `M > 0` |

**Assumptions:** Constant monthly savings, no interest. `months=0` implies purchase now, without future contributions. `current_savings` means savings the user is willing to use for this goal; do not assume all bank funds are available. If No, show budgeting **only as an optional invitation**, not an automatic flow.

## Model 3. Bill Splitting

**Purpose:** Allow more flexible LLM reasoning and clarification about participants, shared items, mixed payers, tax/tip, ratios and custom agreements. Python still verifies totals and arithmetic.

The **LLM should first interpret the scenario**, explicitly ask about missing rules if they affect the split, then call appropriate arithmetic tools. Do not force every story into the equal or itemized tool.

| Function | Inputs | Calculation |
|---|---|---|
| `split_bill(method='equal')` | Total bill, names | Divide equally, reconcile rounding cents |
| `split_bill(method='itemized')` | Items with `amount` and `shared_by`, optional tax/tip | Divide shared items equally; allocate tax/tip in proportion to pretax allocated item costs (default in this tool; confirm if unclear) |
| `split_custom()` | Total and explicitly agreed nonnegative weights by person | Allocate `total * weight/sum(weights)` and reconcile cents |
| `settle_payments()` | Amount each owes and actually paid | `net=paid-owed`; transfer from negative to positive balances |

**Important:** `settle_payments` requires total amounts paid to equal total owed. It computes a valid settlement set, not necessarily the minimum transaction count. The model does not automate transfers. If users need unusual allocations (for instance one person covers all drinks, a guest is exempt from tax, a coupon applies to a subset), the agent must ask clarifying questions and derive agreed final shares before selecting a tool. The current functions do **not** implement arbitrary conditional receipt policies automatically.

## Model 4. Basic Loan / Credit Card Repayment

**Purpose:** Determine monthly payment required for a deadline, time to repay with a chosen monthly payment, and how total interest changes across payment amounts or timelines.

**Required:** Initial balance `B`, annual percentage rate `APR`. Either a monthly payment `P` or desired months `N` for a payoff analysis.

`r = APR / 1200` (APR supplied as percentage)

`monthly_interest = balance * r`

`next_balance = max(0, balance + monthly_interest - monthly_payment)`

To finish in N months at fixed APR:

`monthly_payment = B*r/(1-(1+r)^(-N))` (or `B/N` if `r=0`), rounded up to cents.

For a given monthly payment, iterate the balance recurrence until paid off, using a smaller final payment as necessary.

`total_interest = sum(monthly_interest over repayment months)`

`total_repayment = original_balance + total_interest`

**Functions:**

- `calculate_debt_repayment(balance, apr, monthly_payment=...)`: payoff months, total interest, monthly interest, or inability to pay off if payment <= initial monthly interest.
- `calculate_debt_repayment(balance, apr, payoff_months=...)`: required monthly payment, total interest.
- `compare_debt_payments(balance, apr, monthly_payments=[...])`: compare payment sizes, time to finish and total interest.
- `compare_debt_payments(balance, apr, payoff_months_options=[...])`: compare repayment timelines, monthly cost and total interest.

**Assumptions:** Fixed APR, monthly compounding/interest and payment at month end, no fees, no new charges, no grace periods, no variable minimum payment rules. For credit cards, this is an **illustrative repayment model**, not a precise statement calculation. Paying the full statement balance within the grace period may avoid purchase interest.

## Proposed LLM Tool Policy (not yet wired)

1. Read known user/profile fields, then match their question to a model and desired output.
2. Ask only for missing data necessary to calculate the requested result. In bill splitting, ask for unclear cost-sharing *rules*, rather than guessing.
3. Never invent income, spending, existing savings, APR, allocations or payer amounts. Keep explicit estimates distinguishable from known facts.
4. Let Python perform final arithmetic, especially dollar allocations and interest. Use the LLM for scenario interpretation, choice of method, and user-facing explanation.
5. Return concise result plus editable assumptions. If a purchase goal is not feasible, offer optional budgeting.

## Quick usage

```python
from financial_tools import calculate_cash_flow, calculate_savings, split_bill, split_custom, settle_payments, calculate_debt_repayment, compare_debt_payments

calculate_cash_flow(fixed_income=2000, variable_income=300, fixed_costs=1200, variable_costs=900,
    expense_categories=[
        {'name':'rent','amount':1200,'flexibility':'essential'},
        {'name':'groceries','amount':400,'flexibility':'adjustable'},
        {'name':'entertainment','amount':500,'flexibility':'discretionary','proposed_reduction':100}])
calculate_savings('affordability', current_savings=300, monthly_income=2000, monthly_spending=1500, months=2, target=1200)
split_bill('equal', ['A','B','C'], total=120)
split_custom(120, {'A':2,'B':1,'C':1})
settle_payments({'A':40,'B':40,'C':40}, {'A':80,'B':40,'C':0})
compare_debt_payments(2000,24, monthly_payments=[100,200,300])
compare_debt_payments(2000,24, payoff_months_options=[12,24,36])
```

Tests: `cd /mnt/data/pennyscope_models && python -m unittest -v`.
