"""Predefined selection registries. Factors have no permanent input/output role.

Target-specific input alternatives are shared by extraction and calculation.
Existing calculators continue to own financial arithmetic.
"""
from dataclasses import dataclass
from types import MappingProxyType
from pathlib import Path

MODEL_DESCRIPTIONS = {section.split("`",2)[1]: section.split("\n\n",1)[1].split("### Routing Rules")[0].strip()
                      for section in Path(__file__).with_name("routing_prompt.txt").read_text().split("### Model ")[1:]}


@dataclass(frozen=True)
class ModelRegistry:
    model: str
    factors: object
    targets: tuple[str, ...]
    notes: tuple[str, ...] = ()
    aliases: object = None

    def required_inputs(self, target, values):
        return required_inputs(self.model, target, values)

    def selection_schema(self):
        return {'model': self.model, 'description':MODEL_DESCRIPTIONS[self.model], 'factors': dict(self.factors),
                'supported_targets': list(self.targets), 'aliases': dict(self.aliases or {}),
                'interpretation_notes': list(self.notes)}


def registry(model, factors, targets, notes=(), aliases=None):
    return ModelRegistry(model, MappingProxyType(factors), tuple(targets), tuple(notes), MappingProxyType(aliases or {}))


BUDGET = registry('budget_cash_flow', {
    'fixed_income':'Income explicitly labeled fixed; never a generic total', 'variable_income':'Income explicitly labeled variable; never a generic total',
    'income_entries':'Structured income amounts with raw frequency; category only if explicitly stated',
    'fixed_costs':'Expenses explicitly labeled fixed; not total spending', 'variable_costs':'Expenses explicitly labeled variable; not total spending',
    'spending_entries':'Structured expenses with raw frequency; category only if explicitly stated',
    'expense_categories':'Itemized spending categories; does not imply a complete total',
    'expense_adjustments':'User-specified changes to existing spending',
    'monthly_income':'Total monthly income, only if already supplied as a monthly amount',
    'monthly_expenses':'Total monthly expenses', 'monthly_spending':'Normalized total monthly spending',
    'monthly_surplus':'Income remaining after current expenses', 'recurring_cost':'Proposed ongoing charge with its stated unit',
    'replaced_recurring_cost':'Existing monthly charge that the proposed recurring_cost REPLACES, not total spending',
    'spending_change':'Proposed monthly spending adjustment', 'income_change':'Existing monthly income-change scenario factor',
    'spending_change_entries':'Proposed nonmonthly spending changes with raw frequencies',
    'projected_surplus':'Monthly surplus after proposed changes',
    'affordability_status':'Whether an ongoing expense fits the cash flow',
}, ['monthly_surplus','projected_surplus','affordability_status'], [
    'Preserve weekly, biweekly, semimonthly, monthly, quarterly and annual frequencies. Do not normalize or calculate.',
    'Use income_entries/spending_entries for nonmonthly amounts, not a calculated monthly total.',
    'Partial expense categories are not a complete spending total. Do not invent the missing total.',
    'Generic total income/spending belongs to total factors, not fixed/variable buckets; explicit category evidence is mandatory.',
    'A proposed new charge is recurring_cost or spending_change_entries, not a one-time goal.',
    'For replacing one monthly charge with another, retain recurring_cost=new amount and replaced_recurring_cost=old amount. Do not subtract during extraction.',
    'Rent alone is not fixed_costs or a complete monthly expense total. For a move from $1000 rent to $1400 rent use replaced_recurring_cost=1000 and recurring_cost=1400; income and surplus remain unknown.',
], {'monthly_expenses':'monthly_spending'})

SAVINGS = registry('savings_goal', {
    'current_savings':'Existing savings balance', 'available_savings':'Savings explicitly available for this goal',
    'savings_floor_to_keep':'Savings the user wants to protect', 'goal_amount':'Purchase price or savings target',
    'target_amount':'Existing alternate target-amount ID', 'goal_deadline':'Stated time or date for reaching the goal',
    'goal_description':'Description of the one-time goal', 'monthly_contribution':'Monthly amount contributed',
    'monthly_income':'Monthly income when relevant', 'monthly_expenses':'Monthly spending when relevant',
    'spending_entries':'Complete expense breakdown supplied as separate amounts and frequencies; do not sum in extraction',
    'contribution_entries':'Raw deposit schedule with amount, frequency and count; nonmonthly exact schedules are preserved for a coverage-gap response, not converted to months',
    'contribution_months':'Number of monthly saving periods: supplied count, or a calendar assumption added by code after extraction',
    'monthly_spending':'Existing spending alias', 'monthly_savings':'Existing contribution alias',
    'months':'Existing duration alias', 'target':'Existing target-amount alias',
    'monthly_surplus':'Income remaining after expenses', 'projected_savings':'Future savings balance',
    'required_monthly_savings':'Monthly contribution required to reach the goal',
    'months_to_goal':'Time to reach the goal; not a user-specified deadline', 'affordability_status':'Whether the goal is achievable',
    'shortfall':'Difference between available funds and target',
}, ['projected_savings','required_monthly_savings','monthly_contribution','months_to_goal','goal_deadline','affordability_status','shortfall'], [
    'A contribution toward a one-time goal belongs to this selected model even when monthly.',
    'For rent plus spending on everything else, keep the separate literals in spending_entries (no invented fixed/variable categories). Never emit their computed sum as known monthly_expenses.',
    'A partial expense list is not a complete spending total. Use spending_entries only for an explicitly complete breakdown.',
    'Keep next March as goal_deadline text; never invent a duration or contribution count. Extract contribution_months only for an explicit supplied count; code may add a labeled calendar assumption afterward.',
    'Keep savings holdings distinct from permission to spend them; do not assume all holdings are available.',
    'The target is not an input to ask the user for. Do not fabricate a deadline when time to goal is the target.',
    'Preserve dates and durations; do not calculate a number of months from a date.',
    'Today is goal_deadline=0 months (no future contributions). Do not request contribution capacity for a purchase today.',
    'Weekly deposits with an exact count belong in contribution_entries=[{amount,frequency,count}], not income_entries or monthly_contribution. Monthly-only calculator coverage is checked in code.',
    'A supplied horizon such as want $1200 in five months is goal_deadline=5 months, not months_to_goal. months_to_goal is the target when asking how long.',
], {'target_amount':'goal_amount','monthly_spending':'monthly_expenses','monthly_savings':'monthly_contribution','months':'goal_deadline','target':'goal_amount'})

BILLS = registry('bill_split', {
    'total_bill':'Total expense to divide', 'participants':'Explicit people or an anonymous participant count',
    'split_method':'Equal, itemized, or explicitly agreed custom allocation',
    'items':'Individual expenses and their assigned participants', 'shared_items':'Items shared among specified people',
    'tax_and_tip_amount':'Combined tax and tip when only the combined amount is supplied; do not invent its components',
    'tax_amount':'Tax on the bill', 'tip_amount':'Tip on the bill',
    'split_weights':'Explicitly agreed allocation weights', 'amounts_paid':'Amount each person already paid',
    'amounts_owed':'Amount each person is responsible for', 'settlements':'Transfers needed to settle balances',
    'total':'Existing total_bill alias', 'people':'Existing participants alias',
    'method':'Existing split_method alias','tax':'Existing tax_amount alias',
    'tip':'Existing tip_amount alias','weights':'Existing split_weights alias',
}, ['amounts_owed','settlements'], [
    'Preserve equal, itemized, custom/weighted and settlement operations using split_method and target.',
    'Named participants must be retained as a JSON name list (use me for the user); an anonymous explicit count may remain numeric. Collections use native item keys amount and shared_by.',
    'Do not treat a shared item price as the whole bill total. For an itemized scenario, omit total_bill unless the complete total was stated.',
    'A combined tax/tip amount belongs in tax_and_tip_amount; its separate components are unknown and unnecessary when both use the same allocation rule.',
    'Item entries should include name, amount and shared_by with source-grounded ownership. Equivalent active and possessive wording expresses the same assignment.',
    'No tax or tip means explicit zero, not missing. Item ownership entails an itemized split method; different orders alone do not establish the split agreement.',
    'For someone paid the whole bill, amounts_paid may contain only that payer. The verifier can infer unpaid participant zeros from the whole-bill statement; do not invent payments.',
    'Do not invent sharing rules, weights, participants or payments. Four unnamed people is count=4, not invented names.',
    'Preserve item ownership, shared items, tax and tip evidence. Do not calculate allocations or settlements.',
], {'total':'total_bill','people':'participants','method':'split_method','tax':'tax_amount','tip':'tip_amount','weights':'split_weights'})

DEBT = registry('debt_repayment', {
    'principal_balance':'Outstanding debt principal', 'balance':'Existing native alias for principal_balance',
    'apr':'Annual percentage number as stated: 8% is value=8, unit=%, never 0.08', 'monthly_payment':'Stated monthly repayment',
    'payoff_months':'Desired repayment duration', 'monthly_interest':'Monthly interest expense',
    'total_interest':'Interest across the repayment schedule', 'total_repayment':'Principal plus total interest',
    'estimated_payoff_months':'Calculated repayment duration', 'required_monthly_payment':'Payment needed for a target duration',
}, ['monthly_interest','estimated_payoff_months','required_monthly_payment','total_interest','total_repayment'], [
    'Never invent APR, monthly payments or payoff periods. Do not calculate interest or a payment.',
    'When payment is the target, do not treat it as a value the user must provide.',
], {'balance':'principal_balance'})

REGISTRIES = MappingProxyType({m.model:m for m in (BUDGET,SAVINGS,BILLS,DEBT)})


def get_registry(model):
    """Real Python branch boundary. Unknown IDs never reach factor extraction."""
    try:return REGISTRIES[model]
    except (KeyError,TypeError):raise ValueError('Unsupported selected model') from None


# Each group is OR across alternatives, AND within an alternative. These are
# evidence requirements, not default values or a second calculation engine.
INCOME = (('monthly_income',), ('income_entries',), ('fixed_income','variable_income'))
SPENDING = (('monthly_spending',), ('spending_entries',), ('fixed_costs','variable_costs'))
CONTRIBUTION = (('monthly_contribution',), ('monthly_surplus',), ('monthly_income','monthly_expenses'), ('monthly_income','spending_entries'))


def required_inputs(model, target, values):
    if target not in get_registry(model).targets:
        raise ValueError('Unsupported selected target')
    if model == 'budget_cash_flow':
        if target == 'monthly_surplus' or values.get('expense_adjustments') is not None:
            groups = [INCOME, SPENDING]
        else:
            groups = [(('monthly_surplus',), *(income+spending for income in INCOME for spending in SPENDING))]
        if target in ('projected_surplus','affordability_status'):
            groups.append((('recurring_cost',), ('spending_change',), ('spending_change_entries',),
                           ('income_change',), ('expense_adjustments',)))
        return groups
    if model == 'savings_goal':
        groups = [(('current_savings',), ('available_savings',))]
        if target != 'projected_savings': groups.append((('goal_amount',),))
        if target not in ('months_to_goal','goal_deadline'): groups.append((('goal_deadline',), ('contribution_months',)))
        if target not in ('required_monthly_savings','monthly_contribution') and not (target in ('affordability_status','shortfall','projected_savings') and (values.get('goal_deadline')==0 or values.get('contribution_months')==0)): groups.append(CONTRIBUTION)
        return groups
    if model == 'debt_repayment':
        groups = [(('principal_balance',),), (('apr',),)]
        if target == 'required_monthly_payment': groups.append((('payoff_months',),))
        elif target == 'estimated_payoff_months': groups.append((('monthly_payment',),))
        elif target != 'monthly_interest': groups.append((('monthly_payment',), ('payoff_months',)))
        return groups
    if target == 'settlements' and values.get('amounts_owed') is not None:
        return [(('amounts_owed',),), (('amounts_paid',),)]
    groups = [(('split_method',),)]
    method = values.get('split_method')
    if method in ('custom','weighted'):
        groups += [(('total_bill',),), (('split_weights',),)]
    else:
        groups += [(('participants',),)]
        if method == 'equal': groups.append((('total_bill',),))
        elif method == 'itemized': groups.append((('items',), ('shared_items',)))
    if target == 'settlements': groups.append((('amounts_paid',),))
    return groups
