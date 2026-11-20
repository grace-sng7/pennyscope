"""Decision path: classify -> model inputs -> spreadsheet formulas, or free thinking.

The LLM is mocked. Each exemplar's mocked extraction is the "Given variables"
column of the Formula and Exemplar Review sheet, so these tests check routing,
required-input questions and the Python formula results, not the LLM.
"""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend_reference'))
import gemini_gateway
import penny_pipeline
from main import app

DATE = dict(reference_date='2026-11-20', timezone='America/New_York')


def fact(variable, value, how='stated'):
    return dict(variable=variable, value=value, how=how, note='test')


class FakeLLM:
    """Answers each stage from a script: model, then extraction(s)."""
    def __init__(self, model, *extractions, free='ANSWER: Here is a free-form answer.'):
        self.model, self.extractions, self.free = model, list(extractions), free
        self.stages = []

    def call_json(self, system, prompt, *, stage, response_schema=None):
        self.stages.append(stage)
        if stage == 'model_routing':
            return {'model': self.model}
        if stage == 'factor_extraction':
            return self.extractions.pop(0)
        return {'text': 'Explanation from the computed numbers.', 'suggestions': ['What if it costs more?']}

    def call_text(self, system, prompt, *, stage):
        self.stages.append(stage)
        return self.free


class Pipeline(unittest.TestCase):
    def run_case(self, question, llm, reply=None):
        with TestClient(app) as client, patch.object(gemini_gateway, 'call_json', llm.call_json), \
                patch.object(gemini_gateway, 'call_text', llm.call_text):
            ex = client.post('/extract', json=dict(user_message=question, **DATE)).json()
            if reply is not None:
                ex = client.post('/correct', json=dict(user_message=question, previous_extraction=ex, user_correction=reply, **DATE)).json()
            if ex.get('chat_fallback') or ex['clarification_questions']:
                return ex, None
            meta = {k: v for k, v in ex.items() if k not in ('assumptions', 'clarification_questions')}
            calc = client.post('/calculate', json=dict(original_question=question, assumptions=ex['assumptions'], extraction_meta=meta))
            self.assertEqual(calc.status_code, 200, calc.text)
            return ex, calc.json()

    def result(self, calc, name):
        value = next(f['value'] for f in calc['factors'] if f['variable'] == name)
        return json.loads(value) if isinstance(value, str) and value[:1] in '[{' else value

    # ---- Budget & Cash Flow
    def test_B1_monthly_surplus(self):
        llm = FakeLLM('budget_cash_flow', dict(target='monthly_surplus', facts=[fact('monthly_income', 2400), fact('monthly_spending', 1850)]))
        _, calc = self.run_case('I take home $2,400 a month and spend $1,850 total each month. How much do I have left?', llm)
        self.assertEqual(self.result(calc, 'monthly_surplus'), 550)
        self.assertEqual(calc['model'], 'budget_cash_flow')
        self.assertIn('narrative', calc)

    def test_B2_replaced_plan(self):
        llm = FakeLLM('budget_cash_flow', dict(target='projected_surplus', facts=[
            fact('monthly_surplus', 300), fact('replaced_recurring_cost', 45), fact('recurring_cost', 70), fact('recurring_cost_frequency', 'monthly', 'inferred')]))
        _, calc = self.run_case('...switch to a $70 plan...', llm)
        self.assertEqual(self.result(calc, 'spending_change'), 25)
        self.assertEqual(self.result(calc, 'projected_surplus'), 275)

    def test_B3_asks_for_surplus_then_calculates(self):
        script = lambda: FakeLLM('budget_cash_flow',
            dict(target='affordability_status', facts=[fact('replaced_recurring_cost', 1000), fact('recurring_cost', 1400)]),
            dict(target='affordability_status', facts=[fact('monthly_surplus', 500)]))
        q = 'I want to move to a $1,400/month apartment in February. I currently pay $1,000 in rent. Can I swing it?'
        ex, calc = self.run_case(q, script())
        self.assertIsNone(calc)
        self.assertEqual([c['target_variable'] for c in ex['clarification_questions']], ['monthly_surplus'])
        _, calc = self.run_case(q, script(), reply='$500')
        self.assertEqual(self.result(calc, 'projected_surplus'), 100)
        self.assertEqual(self.result(calc, 'affordability_status'), 'Yes')

    def test_B4_partial_expense_asks_total(self):
        llm = FakeLLM('budget_cash_flow', dict(target='monthly_surplus', facts=[
            fact('monthly_income', 2000), fact('expense_items', [{'name': 'car insurance', 'amount': 150, 'frequency': 'monthly'}])]))
        ex, calc = self.run_case('I take home $2,000 a month. My car insurance is $150 a month...', llm)
        self.assertIsNone(calc)
        self.assertEqual([c['target_variable'] for c in ex['clarification_questions']], ['monthly_spending'])

    # ---- Savings
    def test_S1_required_monthly(self):
        llm = FakeLLM('savings_goal', dict(target='required_monthly_savings', facts=[fact('available_savings', 200), fact('goal_amount', 1200), fact('months', 5)]))
        _, calc = self.run_case('...', llm)
        self.assertEqual(self.result(calc, 'required_monthly_savings'), 200)

    def test_S2_projected(self):
        llm = FakeLLM('savings_goal', dict(target='projected_savings', facts=[fact('available_savings', 300), fact('monthly_contribution', 150), fact('months', 4)]))
        _, calc = self.run_case('...', llm)
        self.assertEqual(self.result(calc, 'projected_savings'), 900)

    def test_S3_purchase_today_shortfall(self):
        llm = FakeLLM('savings_goal', dict(target='affordability_status', facts=[fact('available_savings', 750), fact('goal_amount', 900), fact('months', 0)]))
        _, calc = self.run_case('...', llm)
        self.assertEqual(self.result(calc, 'affordability_status'), 'No')
        self.assertEqual(self.result(calc, 'shortfall'), 150)

    def test_affordable_purchase_headline_shows_projected_savings(self):
        llm = FakeLLM('savings_goal', dict(target='affordability_status', facts=[
            fact('monthly_income', 2400), fact('monthly_spending', 1600), fact('available_savings', 900), fact('goal_amount', 2500), fact('months', 4)]))
        _, calc = self.run_case('Can I afford a $2,500 laptop by next March?', llm)
        self.assertEqual(calc['answer']['headline'], 'Affordability status: Yes. Projected savings: $4,100.00')

    def test_S4_weekly_deposits(self):
        llm = FakeLLM('savings_goal', dict(target='projected_savings', facts=[
            fact('available_savings', 100), fact('deposit_amount', 60), fact('deposit_frequency', 'weekly'), fact('deposit_count', 8)]))
        _, calc = self.run_case('...', llm)
        self.assertEqual(self.result(calc, 'projected_savings'), 580)

    # ---- Bill splitting
    def test_BL1_equal(self):
        llm = FakeLLM('bill_split', dict(target='amounts_owed', facts=[fact('total_bill', 96), fact('participants', 3), fact('split_method', 'equal')]))
        _, calc = self.run_case('...', llm)
        self.assertEqual(set(self.result(calc, 'amounts_owed').values()), {'32.00'})

    def test_BL2_itemized(self):
        llm = FakeLLM('bill_split', dict(target='amounts_owed', facts=[
            fact('participants', ['Maya', 'me']), fact('split_method', 'itemized', 'inferred'), fact('tax_amount', 0), fact('tip_amount', 0),
            fact('items', [{'name': 'pizza', 'amount': 24, 'shared_by': ['Maya', 'me']}, {'name': 'drink', 'amount': 6, 'shared_by': ['me']}])]))
        _, calc = self.run_case('...', llm)
        self.assertEqual(self.result(calc, 'amounts_owed'), {'Maya': '12.00', 'me': '18.00'})
        self.assertIn('You: $18.00', calc['answer']['headline'])

    def test_BL3_settlement_infers_zero_payments(self):
        llm = FakeLLM('bill_split', dict(target='settlements', facts=[
            fact('total_bill', 90), fact('participants', ['Alex', 'Jamie', 'me']), fact('split_method', 'equal'), fact('amounts_paid', {'Alex': 90})]))
        _, calc = self.run_case('...', llm)
        transfers = self.result(calc, 'settlements')
        self.assertEqual(sorted((t['from'], t['to'], t['amount']) for t in transfers), [('Jamie', 'Alex', '30.00'), ('me', 'Alex', '30.00')])

    def test_BL4_asks_split_method(self):
        llm = FakeLLM('bill_split', dict(target='amounts_owed', facts=[fact('total_bill', 84), fact('participants', 3)]))
        ex, calc = self.run_case('...', llm)
        self.assertIsNone(calc)
        self.assertEqual(ex['clarification_questions'][0]['question'], 'Do you want to split it evenly or by what each person ordered?')

    # ---- Debt
    def test_D1_zero_apr_payoff(self):
        llm = FakeLLM('debt_repayment', dict(target='estimated_payoff_months', facts=[fact('principal_balance', 1200), fact('apr', 0), fact('monthly_payment', 200)]))
        _, calc = self.run_case('...', llm)
        self.assertEqual(self.result(calc, 'estimated_payoff_months'), 6)

    def test_D2_payoff_and_total_interest(self):
        llm = FakeLLM('debt_repayment', dict(target='estimated_payoff_months', supporting_targets=['total_interest'],
                                             facts=[fact('principal_balance', 1000), fact('apr', 12), fact('monthly_payment', 510)]))
        _, calc = self.run_case('...', llm)
        self.assertEqual(self.result(calc, 'estimated_payoff_months'), 2)
        self.assertEqual(self.result(calc, 'total_interest'), 15)
        self.assertEqual(calc['answer']['headline'], 'Estimated payoff months: 2 months. Total interest: $15.00')

    def test_D3_required_payment(self):
        llm = FakeLLM('debt_repayment', dict(target='required_monthly_payment', facts=[fact('principal_balance', 900), fact('apr', 0), fact('payoff_months', 6)]))
        _, calc = self.run_case('...', llm)
        self.assertEqual(self.result(calc, 'required_monthly_payment'), 150)

    def test_D4_asks_apr(self):
        llm = FakeLLM('debt_repayment', dict(target='estimated_payoff_months', facts=[fact('principal_balance', 5000), fact('monthly_payment', 200)]))
        ex, calc = self.run_case('...', llm)
        self.assertIsNone(calc)
        self.assertEqual(ex['clarification_questions'][0]['question'], 'What’s the APR on that balance?')

    # ---- Fallback
    def test_no_model_uses_free_thinking(self):
        llm = FakeLLM('none', free='ANSWER: Index funds spread risk across many companies.')
        ex, calc = self.run_case('Should I put my bonus in an index fund?', llm)
        self.assertIsNone(calc)
        self.assertEqual(ex['chat_fallback'], {'kind': 'answer', 'text': 'Index funds spread risk across many companies.'})
        self.assertNotIn('factor_extraction', llm.stages)

    def test_new_question_mid_chat_switches_model(self):
        llm = FakeLLM('debt_repayment', dict(target='estimated_payoff_months', facts=[fact('principal_balance', 5000), fact('monthly_payment', 200)]))
        with TestClient(app) as client, patch.object(gemini_gateway, 'call_json', llm.call_json):
            ex = client.post('/extract', json=dict(user_message='I owe $5,000...', **DATE)).json()
            llm.model = 'bill_split'
            llm.extractions.append(dict(target='amounts_owed', facts=[fact('total_bill', 60), fact('participants', 2), fact('split_method', 'equal')]))
            ex = client.post('/correct', json=dict(user_message='I owe $5,000...', previous_extraction=ex, user_correction='Different question: split $60 evenly between 2 of us.', **DATE)).json()
        self.assertEqual(ex['model'], 'bill_split')
        self.assertNotIn('principal_balance', [a['variable'] for a in ex['assumptions']])

    def test_unknown_inputs_and_bad_values_are_dropped(self):
        facts = penny_pipeline._clean('debt_repayment', [fact('principal_balance', '$1,000'), fact('apr', '12%'), fact('goal_amount', 5), fact('monthly_payment', -3)])
        self.assertEqual({k: v['value'] for k, v in facts.items()}, {'principal_balance': 1000, 'apr': 12})


if __name__ == '__main__':
    unittest.main()
