"""Predefined selection registries. Factors have no permanent input/output role.

This iteration specifies selection/extraction only. Required-input alternatives
and calculator/response execution remain owned by the existing downstream code.
"""
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ModelRegistry:
    model: str
    factors: object
    targets: tuple[str, ...]
    notes: tuple[str, ...] = ()
    aliases: object = None

    def selection_schema(self):
        return {'model': self.model, 'factors': dict(self.factors),
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
], {'monthly_expenses':'monthly_spending'})

SAVINGS = registry('savings_goal', {
    'current_savings':'Existing savings balance', 'available_savings':'Savings explicitly available for this goal',
    'savings_floor_to_keep':'Savings the user wants to protect', 'goal_amount':'Purchase price or savings target',
    'target_amount':'Existing alternate target-amount ID', 'goal_deadline':'Stated time or date for reaching the goal',
    'goal_description':'Description of the one-time goal', 'monthly_contribution':'Monthly amount contributed',
    'monthly_income':'Monthly income when relevant', 'monthly_expenses':'Monthly spending when relevant',
    'monthly_spending':'Existing spending alias', 'monthly_savings':'Existing contribution alias',
    'months':'Existing duration alias', 'target':'Existing target-amount alias',
    'monthly_surplus':'Income remaining after expenses', 'projected_savings':'Future savings balance',
    'required_monthly_savings':'Monthly contribution required to reach the goal',
    'months_to_goal':'Time to reach the goal; not a user-specified deadline', 'affordability_status':'Whether the goal is achievable',
    'shortfall':'Difference between available funds and target',
}, ['projected_savings','required_monthly_savings','monthly_contribution','months_to_goal','goal_deadline','affordability_status','shortfall'], [
    'A contribution toward a one-time goal belongs to this selected model even when monthly.',
    'Keep savings holdings distinct from permission to spend them; do not assume all holdings are available.',
    'The target is not an input to ask the user for. Do not fabricate a deadline when time to goal is the target.',
    'Preserve dates and durations; do not calculate a number of months from a date.',
    'A supplied horizon such as want $1200 in five months is goal_deadline=5 months, not months_to_goal. months_to_goal is the target when asking how long.',
], {'target_amount':'goal_amount','monthly_spending':'monthly_expenses','monthly_savings':'monthly_contribution','months':'goal_deadline','target':'goal_amount'})

BILLS = registry('bill_split', {
    'total_bill':'Total expense to divide', 'participants':'Explicit people or an anonymous participant count',
    'split_method':'Equal, itemized, or explicitly agreed custom allocation',
    'items':'Individual expenses and their assigned participants', 'shared_items':'Items shared among specified people',
    'tax_amount':'Tax on the bill', 'tip_amount':'Tip on the bill',
    'split_weights':'Explicitly agreed allocation weights', 'amounts_paid':'Amount each person already paid',
    'amounts_owed':'Amount each person is responsible for', 'settlements':'Transfers needed to settle balances',
    'total':'Existing total_bill alias', 'people':'Existing participants alias',
    'method':'Existing split_method alias','tax':'Existing tax_amount alias',
    'tip':'Existing tip_amount alias','weights':'Existing split_weights alias',
}, ['amounts_owed','settlements'], [
    'Preserve equal, itemized, custom/weighted and settlement operations using split_method and target.',
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
