import unittest
from financial_tools import (calculate_cash_flow, calculate_savings, split_bill,
                             settle_payments, split_custom, calculate_debt_repayment, compare_debt_payments)

class FinancialToolsTests(unittest.TestCase):
    def test_cashflow(self):
        x = calculate_cash_flow(2000, 1500, spending_change=70)
        self.assertEqual(x['monthly_surplus'], '500.00')
        self.assertEqual(x['scenario_monthly_surplus'], '430.00')
    def test_normalize(self):
        x = calculate_cash_flow(income_entries=[{'amount':1200, 'frequency':'biweekly', 'category':'fixed'}],
                                spending_entries=[{'amount':1000, 'category':'fixed'}])
        self.assertEqual(x['monthly_income'], '2600.00')
    def test_affordability(self):
        x = calculate_savings('affordability', current_savings=300, monthly_income=2000,
                              monthly_spending=1500, months=2, target=1200)
        self.assertTrue(x['affordable'])
        self.assertEqual(x['remaining_after_goal'], '100.00')
    def test_savings_inverse(self):
        self.assertEqual(calculate_savings('monthly_required', current_savings=300,
            months=6, target=3000)['required_monthly_savings'], '450.00')
        self.assertEqual(calculate_savings('months_required', current_savings=300,
            monthly_savings=500, target=1200)['months_required'], 2)
    def test_today(self):
        self.assertFalse(calculate_savings('affordability', current_savings=300,
             monthly_savings=500, months=0, target=1200)['affordable'])
    def test_split_equal_cents(self):
        x = split_bill('equal', ['A','B','C'], total='100.00')
        self.assertEqual(list(x['amounts_owed'].values()), ['33.34','33.33','33.33'])
    def test_itemized(self):
        x = split_bill('itemized', ['A','B'], items=[{'amount':30,'shared_by':['A']},
            {'amount':20,'shared_by':['B']}, {'amount':10,'shared_by':['A','B']}], tax=6, tip=6)
        self.assertEqual(x['total'], '72.00')
        self.assertEqual(sum(float(v) for v in x['amounts_owed'].values()), 72.0)
    def test_settlement(self):
        x = settle_payments({'A':40,'B':40,'C':40},{'A':80,'B':40,'C':0})
        self.assertEqual(x['transfers'], [{'from':'C','to':'A','amount':'40.00'}])
    def test_debt_interest_and_payoff(self):
        x = calculate_debt_repayment(2000,24,monthly_payment=200)
        self.assertEqual(x['first_month_interest'], '40.00')
        self.assertTrue(x['payoff_possible'])
        self.assertEqual(x['payoff_months'], 12)
    def test_debt_nonamortizing(self):
        self.assertFalse(calculate_debt_repayment(2000,24,monthly_payment=40)['payoff_possible'])
    def test_debt_required_payment(self):
        x=calculate_debt_repayment(1200,0,payoff_months=12)
        self.assertEqual(x['required_monthly_payment'],'100.00')
    def test_debt_zero_balance(self):
        self.assertEqual(calculate_debt_repayment(0,24,payoff_months=12)['payoff_months'],0)

    def test_four_bucket_profile(self):
        x=calculate_cash_flow(fixed_income=2000, variable_income=300,
                              fixed_costs=1200, variable_costs=900)
        self.assertEqual(x['monthly_surplus'],'200.00')
        self.assertEqual(x['surplus_excluding_variable_income'],'-100.00')
    def test_category_savings_scenario(self):
        x=calculate_cash_flow(fixed_income=2000, variable_income=300,
                              fixed_costs=1200,variable_costs=900,
                              expense_categories=[
                                  {'name':'rent','amount':1200,'flexibility':'essential'},
                                  {'name':'groceries','amount':400,'flexibility':'adjustable'},
                                  {'name':'entertainment','amount':500,'flexibility':'discretionary',
                                   'proposed_reduction':100}])
        self.assertEqual(x['scenario_monthly_surplus'],'300.00')
        self.assertEqual(x['spending_by_flexibility']['discretionary'],'500.00')
    def test_category_cannot_double_count(self):
        with self.assertRaises(ValueError):
            calculate_cash_flow(fixed_income=2000,fixed_costs=1000,
                expense_categories=[{'name':'rent','amount':900,'flexibility':'essential'}])
    def test_payment_comparison(self):
        x=compare_debt_payments(2000,24,monthly_payments=[100,200,300])
        self.assertEqual(len(x['scenarios']),3)
        self.assertGreater(float(x['scenarios'][0]['total_interest']),
                           float(x['scenarios'][2]['total_interest']))
        self.assertGreater(x['scenarios'][0]['payoff_months'],
                           x['scenarios'][2]['payoff_months'])
    def test_timeline_comparison(self):
        x=compare_debt_payments(2000,24,payoff_months_options=[12,24])
        self.assertGreater(float(x['scenarios'][1]['total_interest']),
                           float(x['scenarios'][0]['total_interest']))
        self.assertLess(float(x['scenarios'][1]['monthly_payment']),
                        float(x['scenarios'][0]['monthly_payment']))
    def test_unpayable_debt_comparison(self):
        x=compare_debt_payments(2000,24,monthly_payments=[20,200])
        self.assertFalse(x['scenarios'][0]['payoff_possible'])
        self.assertIsNone(x['scenarios'][0]['total_interest'])
    def test_custom_bill_split(self):
        x=split_custom(120,{'A':2,'B':1,'C':1})
        self.assertEqual(x['amounts_owed'],{'A':'60.00','B':'30.00','C':'30.00'})
if __name__ == '__main__': unittest.main()
