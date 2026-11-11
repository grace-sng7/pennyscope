"""Offline architecture and resolution regressions; no provider credentials."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend_reference'))
import orchestration as o
from contract import CalculateResponse, ExtractionResponse


def request():
    values = [('monthly_income',3000,'$/month'),('monthly_expenses',1800,'$/month'),
              ('current_savings',2500,'$'),('goal_amount',1800,'$'),('goal_deadline',6,'months')]
    return {'original_question':'Save for a laptop; preserve all existing savings.',
            'assumptions':[dict(variable=k,value=v,unit=u,source='stated',source_detail='user',edited_by_user=False) for k,v,u in values],
            'parameters':{},'extra_inputs':{},'answers':[],'extraction_meta':{}}


def draft():
    return {'model':'savings_goal','inputs':dict(monthly_income=3000,monthly_expenses=1800,
              current_savings=2500,goal_amount=1800,goal_deadline=6,monthly_contribution=300,use_from_savings=0),
            'bindings':{},'results':{'available':1200,'projected':9999,'gap':0,'remaining':900},
            'headline':'Initial erroneous draft','calculation':'300 * 6','assumptions':[]}


def review():
    return {'decision':'approved','reason_type':'arithmetic','reason':'Use verified result',
            'assumptions':['Existing savings are protected.'],'headline':'Your goal is feasible.',
            'detail':'Income and expenses stay constant.'}


class Integration(unittest.TestCase):
    def setUp(self):
        o.CACHE.clear(); o.PENDING_REVIEWS.clear()

    def test_two_stages_correct_arithmetic_and_slider_no_llm(self):
        with patch.object(o,'call_json',side_effect=[draft(),review()]) as llm:
            r=o.calculate(request())
            CalculateResponse.model_validate(r)
            self.assertEqual(llm.call_count,2)
            self.assertIn('projected', __import__('json').loads(llm.call_args.args[1])['arithmetic_disagreements'])
            self.assertEqual(r['metrics'][1]['value'],'$1,800')
            req=request();req['parameters']={'monthly_contribution':200}
            r=o.calculate(req)
            self.assertEqual(llm.call_count,2)
            self.assertEqual(r['metrics'][1]['value'],'$1,200')
            self.assertIn('No,',r['answer']['headline'])

    def test_ambiguity_blocks_answer_and_sliders(self):
        inspector={'decision':'needs_input','missing_inputs':[{'variable':'available_savings','label':'How much savings may be used?'}]}
        with patch.object(o,'call_json',side_effect=[draft(),inspector]):
            r=o.calculate(request())
        self.assertEqual(r['status'],'needs_input');self.assertNotIn('answer',r)
        self.assertFalse(o.CACHE)

    def test_changed_facts_trigger_fresh_review(self):
        with patch.object(o,'call_json',side_effect=[draft(),review(),{'model':'gap','gap_reason':'Reassessment'}]) as llm:
            o.calculate(request()); req=request();req['assumptions'][0]['value']=2000
            self.assertEqual(o.calculate(req)['status'],'unsupported')
            self.assertEqual(llm.call_count,3)

    def test_invented_input_rejected(self):
        d=draft();d['inputs']['monthly_income']=4000
        with patch.object(o,'call_json',return_value=d),self.assertRaises(HTTPException):o.calculate(request())
        self.assertFalse(o.CACHE)

    def test_recurring_goal_wrong_unit_rejected(self):
        req=request();req['assumptions'][3]['unit']='$/month'
        with patch.object(o,'call_json',return_value=draft()),self.assertRaises(HTTPException):o.calculate(req)

    def test_negative_nan_and_excess_allocation_sliders_rejected(self):
        with patch.object(o,'call_json',side_effect=[draft(),review()]):o.calculate(request())
        for p in [{'monthly_contribution':-1},{'monthly_contribution':float('nan')},
                  {'monthly_contribution':1500},{'use_from_savings':3000},{'unknown':1}]:
            req=request();req['parameters']=p
            with self.assertRaises(HTTPException):o.calculate(req)

    def test_inspector_failure_never_cached(self):
        with patch.object(o,'call_json',side_effect=[draft(),HTTPException(502,'unavailable')]),self.assertRaises(HTTPException):o.calculate(request())
        self.assertFalse(o.CACHE)

    def test_duplicate_and_source_mismatch_rejected(self):
        for variant in ['duplicate','source']:
            req=request()
            if variant=='duplicate':req['assumptions'].append(copy.deepcopy(req['assumptions'][0]))
            else:req['assumptions'][0]['source']='missing'
            with patch.object(o,'call_json') as llm,self.assertRaises(HTTPException):o.calculate(req)
            llm.assert_not_called()

    def test_zero_months_purchase(self):
        d=draft();d['inputs'].update(goal_deadline=0,monthly_contribution=0)
        req=request();req['assumptions'][4]['value']=0
        with patch.object(o,'call_json',side_effect=[d,review()]):
            r=o.calculate(req)
        self.assertEqual(r['metrics'][1]['value'],'$0')

    def test_python_budget_verification(self):
        d={'model':'budget_cash_flow','inputs':{'monthly_income':3000,'monthly_spending':1800},
           'bindings':{'monthly_income':'monthly_income','monthly_spending':'monthly_expenses'},'results':{}}
        with patch.object(o,'call_json',side_effect=[d,review()]):r=o.calculate(request())
        CalculateResponse.model_validate(r)
        self.assertTrue(any(m['label']=='Monthly surplus' and m['value']=='1200.00' for m in r['metrics']))

if __name__=='__main__':unittest.main()

class GatewayChecks(unittest.TestCase):
    def test_transient_failure_retries_once(self):
        import gemini_gateway as g
        import httpx
        response=lambda status, body: httpx.Response(status,json=body,request=httpx.Request('POST','https://example.invalid'))
        ok=response(200,{'candidates':[{'content':{'parts':[{'text':'{"ok": true}'}]}}]})
        with patch.object(Path,'read_text',return_value='{"api_key":"fake-test-only","model_id":"gemini/test"}'),patch.object(g.httpx,'post',side_effect=[response(503,{}),ok]) as post:
            self.assertEqual(g.call_json('system','prompt'),{'ok':True})
            self.assertEqual(post.call_count,2)

    def test_provider_errors_do_not_expose_key(self):
        import gemini_gateway as g
        import httpx
        r=httpx.Response(403,json={'detail':'fake-test-only'},request=httpx.Request('POST','https://example.invalid'))
        with patch.object(Path,'read_text',return_value='{"api_key":"fake-test-only"}'),patch.object(g.httpx,'post',return_value=r) as post,self.assertRaises(HTTPException) as caught:
            g.call_json('system','prompt')
        self.assertEqual(post.call_count,1)
        self.assertNotIn('fake-test-only',caught.exception.detail)

class ReviewBoundaries(unittest.TestCase):
    def setUp(self):o.CACHE.clear(); o.PENDING_REVIEWS.clear()

    def test_expired_review_requires_llm_again(self):
        with patch.object(o,'call_json',side_effect=[draft(),review(),{'model':'gap','gap_reason':'Fresh review'}]) as llm:
            o.calculate(request())
            for entry in o.CACHE.values():entry['time']-=o.TTL+1
            self.assertEqual(o.calculate(request())['status'],'unsupported')
            self.assertEqual(llm.call_count,3)

    def test_protected_savings_cannot_be_spent_with_slider(self):
        with patch.object(o,'call_json',side_effect=[draft(),review()]):r=o.calculate(request())
        self.assertEqual(r['parameters'][1]['max'],0)
        req=request();req['parameters']={'use_from_savings':1}
        with self.assertRaises(HTTPException):o.calculate(req)

    def test_bill_and_debt_verification_render_contract(self):
        for model,inputs in [('bill_split',{'method':'equal','people':['A','B','C'],'total':120}),
                             ('debt_repayment',{'balance':1000,'apr':0,'monthly_payment':100})]:
            o.CACHE.clear(); o.PENDING_REVIEWS.clear();req=request()
            req['assumptions']=[{'variable':k,'value':__import__('json').dumps(v) if isinstance(v,list) else v,'unit':None,'source':'stated','source_detail':'user','edited_by_user':False} for k,v in inputs.items()]
            d={'model':model,'inputs':inputs,'bindings':{k:k for k in inputs},'results':{}}
            with patch.object(o,'call_json',side_effect=[d,review()]):r=o.calculate(req)
            CalculateResponse.model_validate(r)
            if model=='bill_split':self.assertEqual(len([m for m in r['metrics'] if m['value']=='40.00']),3)
            else:self.assertTrue(any(m['label']=='Payoff months' and m['value']=='10' for m in r['metrics']))


class FinalAnswerChecks(unittest.TestCase):
    def test_unverified_numeric_narrative_is_not_displayed(self):
        o.CACHE.clear(); o.PENDING_REVIEWS.clear();req=request()
        d={'model':'budget_cash_flow','inputs':{'monthly_income':3000,'monthly_spending':1800},'bindings':{'monthly_income':'monthly_income','monthly_spending':'monthly_expenses'},'results':{}}
        inspector=review();inspector['headline']='You have $9999 available.'
        with patch.object(o,'call_json',side_effect=[d,inspector]),self.assertRaises(HTTPException):o.calculate(req)
        self.assertFalse(o.CACHE)
