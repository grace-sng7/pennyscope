"""Shared presentation regressions: complete answers, schedules, and isolation."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import answer_presentation as p
import question_approach as q
from test_today_purchase import run_case


def schedule_case(final=580):
    req={'original_question':'My trip fund has $100. I’ll add $60 at the end of every week for the next eight weeks. How much will I have after the eighth deposit?',
         'assumptions':[dict(variable='current_savings',value=100),dict(variable='contribution_entries',value=json.dumps([dict(amount=60,frequency='weekly',count=8)]))]}
    result={'status':'conditional','target_variable':'projected_savings','answer':{'headline':f'You will have ${final} after the eighth deposit.'},'factors':[dict(variable='projected_savings',value=final,unit='$',role='derived',source='inferred',source_detail='Main calculation')],
            'verification':{'status':'unverified','target_variable':'projected_savings','main_value':final,'unit':'$'},'explanations':[{'label':'Main calculation','text':f'100 + 60 × 8 = {final}'}]}
    return req,result

class PresentationRegressions(unittest.TestCase):
    def test_today_preserves_main_sentence_and_grace_funding(self):
        ex,r=run_case();result=r.json()
        self.assertIn('$150',result['answer']['headline']);self.assertNotIn('Affordability status',result['answer']['headline'])
        self.assertEqual(result['visuals']['funding']['short'],150)
        self.assertIn('purchase today',result['narrative']['text'])
        self.assertNotIn('0 months',result['narrative']['text'])
        self.assertEqual(len(result['narrative']['suggestions']),2)

    def test_weekly_schedule_has_amount_count_timeline_and_narrative(self):
        req,result=schedule_case();out=p.attach_scoped(result,req)
        self.assertEqual(out['visuals']['timeline'][-1],dict(deposit=8,balance=580))
        self.assertEqual(out['visuals']['period'],'week')
        self.assertIn('$480',out['narrative']['text']);self.assertIn('8 deposits',out['narrative']['text'])
        self.assertEqual(out['verification']['status'],'unverified')
        self.assertEqual(out['answer'],result['answer'])
        self.assertNotIn('visuals',result)

    def test_conflicting_or_incomplete_schedule_keeps_main_without_conflicting_chart(self):
        req,result=schedule_case(600)
        self.assertNotIn('visuals',p.attach_scoped(result,req))
        self.assertIn('$600',p.attach_scoped(result,req)['answer']['headline'])
        req,result=schedule_case();req['assumptions'][1]['value']='[{"amount":60,"frequency":"weekly"}]'
        self.assertNotIn('visuals',p.attach_scoped(result,req))

    def test_scoped_endpoint_attaches_schedule_without_turning_verification_into_match(self):
        req,_=schedule_case()
        raw=dict(calculation='100 + 60 * 8 = 580',approach='Initial balance plus all deposits',target_variable='projected_savings',headline='You will have $580 after the eighth deposit.',missing_inputs=[],factors=[
            dict(variable='current_savings',value=100,unit='$',role='known',source='stated',source_detail='User balance',evidence_quotes=['My trip fund has $100.']),
            dict(variable='projected_savings',value=580,unit='$',role='derived',source='inferred',source_detail='100 + 60 * 8',evidence_quotes=[])])
        with patch('gemini_gateway.call_json',return_value=raw):out=q.calculate(req)
        self.assertEqual(out['visuals']['timeline'][-1]['balance'],580)
        self.assertEqual(out['verification']['status'],'unverified')
