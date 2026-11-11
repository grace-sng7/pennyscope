import unittest
from agent_app import parse_payload, profile_from_json, DEFAULT_PROFILE
from financial_tools import calculate_cash_flow, calculate_savings, split_bill, settle_payments, compare_debt_payments

class StructureChecks(unittest.TestCase):
    def test_json_profile(self):
        self.assertEqual(profile_from_json('{"fixed_income": 2000, "current_savings": null}'), {'fixed_income': 2000})
    def test_payload(self):
        self.assertEqual(parse_payload('{"balance": 100}'), {'balance': 100})
        with self.assertRaises(ValueError): parse_payload('[1,2]')
    def test_cash_flow(self):
        r = calculate_cash_flow(fixed_income=2000,variable_income=300,fixed_costs=1200,variable_costs=700)
        self.assertEqual(r['monthly_surplus'], '400.00')
    def test_savings(self):
        r = calculate_savings(solve_for='affordability',current_savings=500,monthly_income=2300,monthly_spending=1900,months=4,target=2000)
        self.assertTrue(r['affordable'])
    def test_bill_settlement(self):
        owed = split_bill(method='equal',people=['A','B','C'],total=120)['amounts_owed']
        r = settle_payments(owed,{'A':120,'B':0,'C':0})
        self.assertEqual(sum(float(x['amount']) for x in r['transfers']),80)
    def test_debt(self):
        r = compare_debt_payments(balance=2000,apr=24,monthly_payments=[100,200,300])
        self.assertEqual(len(r['scenarios']),3)

if __name__=='__main__': unittest.main()
