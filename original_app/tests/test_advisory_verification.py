"""End-to-end API regressions for Main-owned answers and advisory verification."""
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import orchestration as o
from main import app


def request():
    values=[('current_savings',350,'$'),('monthly_contribution',125,'$/month'),('goal_deadline',6,'months')]
    return dict(original_question='I have $350 saved and will make six monthly deposits of $125. What will I have?',
                assumptions=[dict(variable=k,value=v,unit=u,source='stated',source_detail='User supplied fact') for k,v,u in values],
                extraction_meta=dict(model='savings_goal',target_variable='projected_savings'))


def draft(value):
    return dict(model='savings_goal',target_variable='projected_savings',
                inputs=dict(solve_for='future_balance',current_savings=350,monthly_savings=125,months=6),
                bindings=dict(current_savings='current_savings',monthly_savings='monthly_contribution',months='goal_deadline'),
                factors=[dict(variable='projected_savings',value=value,unit='$',role='derived',source='inferred',source_detail='Main calculation')],
                results=dict(projected_savings=value,months=999,intermediate_amount=9999),headline=f'You will have ${value:,}.',calculation='Starting balance plus six deposits.',assumptions=[])


class AdvisoryVerification(unittest.TestCase):
    def setUp(self):o.CACHE.clear();o.PENDING_REVIEWS.clear()

    def call(self,value,review=None,verification_error=None):
        review=review or dict(decision='needs_input',reason_type='model_gap',missing_inputs=[],headline='Do not display',assumptions=[])
        with TestClient(app) as client,patch.object(o,'call_json',side_effect=[draft(value),review]):
            if verification_error:
                with patch.object(o,'_verify',side_effect=verification_error):return client.post('/calculate',json=request())
            return client.post('/calculate',json=request())

    def test_1100_matches_despite_other_fields_and_inspector_disagreement(self):
        response=self.call(1100);self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['verification']['status'],'matched')
        self.assertIn('$1,100.00',data['answer']['headline'])
        self.assertEqual(data['verification']['python_value'],1100.0)
        self.assertEqual(data['factors'][0]['value'],1100)

    def test_1200_stays_visible_when_python_returns_1100(self):
        response=self.call(1200);self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['verification']['status'],'mismatch')
        self.assertIn('$1,200.00',data['answer']['headline'])
        self.assertEqual(data['verification']['python_value'],1100.0)
        self.assertEqual(data['factors'][0]['value'],1200)
        self.assertNotIn('$1,100',data['answer']['headline'])

    def test_python_failure_keeps_main_answer_and_marks_unverified(self):
        for error in [ValueError('Unsupported solver'),TypeError('Bad verifier schema'),HTTPException(502,'Unavailable')]:
            o.CACHE.clear()
            response=self.call(1200,verification_error=error)
            self.assertEqual(response.status_code,200)
            data=response.json();self.assertEqual(data['verification']['status'],'unverified')
            self.assertIn('$1,200.00',data['answer']['headline'])
            self.assertEqual(data['factors'][0]['value'],1200)

    def test_inspector_cannot_block_or_rewrite_main(self):
        for review in [dict(decision='unsupported',reason_type='model_gap'),dict(decision='approved',headline='$9999',assumptions=[]),HTTPException(502,'Inspector unavailable')]:
            o.CACHE.clear()
            with patch.object(o,'call_json',side_effect=[draft(1100),review]):response=o.calculate(request())
            self.assertEqual(response['verification']['status'],'matched')
            self.assertIn('$1,100.00',response['answer']['headline']);self.assertNotIn('9999',response['answer']['headline'])

    def test_only_final_shares_and_cent_precision_are_compared(self):
        self.assertEqual(o._disagreements({'amounts_owed':{'A':32,'B':'32.004'},'input':999},{'amounts_owed':{'B':'32.00','A':'32.00'},'metadata':'ignored'},'amounts_owed','$'),[])
        self.assertEqual(o._disagreements({'amounts_owed':{'A':31,'B':33}},{'amounts_owed':{'A':32,'B':32}},'amounts_owed','$'),['amounts_owed.A','amounts_owed.B'])
        self.assertEqual(o._disagreements({'projected_savings':1100},{'projected_savings':'1100.00','months':6,'model':'different'},'projected_savings','$'),[])
        with self.assertRaises(ValueError):o._disagreements({'projected_savings':1100},{'projected_savings':1100},'projected_savings','$/week')

    def test_verifier_uses_user_facts_and_ignores_main_intermediate_inputs(self):
        main=draft(1100);main['inputs']['current_savings']=9999
        main['factors'].append(dict(variable='unused_intermediate',value=99999,unit='text',role='derived',source='inferred',source_detail='Not the requested result'))
        with patch.object(o,'call_json',side_effect=[main,dict(decision='approved')]):response=o.calculate(request())
        self.assertEqual(response['verification']['status'],'matched')
        self.assertEqual(response['verification']['python_value'],1100.0)

    def test_genuine_missing_inputs_still_ask_before_main(self):
        req=request();req['assumptions']=req['assumptions'][:-1]
        with patch.object(o,'call_json') as llm:response=o.calculate(req)
        self.assertEqual(response['status'],'needs_input');llm.assert_not_called()

    def test_bill_split_compares_each_person_and_keeps_main_shares(self):
        import json
        req=dict(original_question='Split the $96 all-inclusive bill equally among A, B and C.',
                 assumptions=[dict(variable=k,value=v,unit=u,source='stated',source_detail='User supplied fact') for k,v,u in [('total_bill',96,'$'),('participants',json.dumps(['A','B','C']),'text'),('split_method','equal','text')]],
                 extraction_meta=dict(model='bill_split',target_variable='amounts_owed'))
        for shares,status in [({'A':32,'B':32,'C':32},'matched'),({'A':31,'B':33,'C':32},'mismatch')]:
            o.CACHE.clear()
            main=dict(model='bill_split',target_variable='amounts_owed',inputs={},bindings={},
                      results={'amounts_owed':shares},factors=[dict(variable='amounts_owed',value=json.dumps(shares),unit='text',role='derived',source='inferred',source_detail='Main shares')],headline='Each person owes the listed share.')
            with patch.object(o,'call_json',side_effect=[main,dict(decision='needs_input',reason_type='model_gap',missing_inputs=[])]):response=o.calculate(req)
            self.assertEqual(response['verification']['status'],status)
            self.assertEqual(json.loads(response['factors'][0]['value']),shares)

    def test_monthly_deposit_count_reaches_main_instead_of_coverage_gap(self):
        import extraction_service
        from test_selection_stages import selected
        question='My fund has $350. I add $125 monthly for six monthly deposits.'
        raw=selected('projected_savings',dict(current_savings=350,contribution_entries=[dict(amount=125,frequency='monthly',count=6)]))
        with patch('gemini_gateway.call_json',side_effect=[{'model':'savings_goal'},raw]):ex=extraction_service.extract(question,'2026-11-16','America/New_York')
        req=dict(original_question=question,assumptions=ex['assumptions'],extraction_meta={k:v for k,v in ex.items() if k not in ('assumptions','clarification_questions')})
        with patch.object(o,'call_json',side_effect=[draft(1100),dict(decision='approved')]):response=o.calculate(req)
        self.assertEqual(response['verification']['status'],'matched')
        self.assertIn('$1,100.00',response['answer']['headline'])

    def test_main_missing_input_unavailable_check_keeps_question_without_inspector(self):
        main=draft(1100)
        main['missing_inputs']=[{'variable':'goal_deadline','label':'How many monthly deposits will you make?'}, {'variable':'monthly_contribution','label':'How much each month?'}]
        with TestClient(app) as client,patch.object(o,'call_json',return_value=main) as llm,patch.object(o,'_verify',side_effect=ValueError('Cannot calculate')) as verify:
            response=client.post('/calculate',json=request())
        self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['status'],'needs_input')
        self.assertEqual(data['message'],'How many monthly deposits will you make?')
        self.assertEqual(len(data['missing_inputs']),1)
        self.assertEqual(data['verification']['context'],'question')
        self.assertEqual(data['verification']['status'],'unverified')
        self.assertIsNone(data['answer']);self.assertEqual(llm.call_count,1);verify.assert_called_once()
        self.assertEqual(llm.call_args.kwargs['stage'],'main_calculation')

    def test_main_missing_input_sufficient_check_keeps_question_with_warning(self):
        main=draft(1100)
        main['missing_inputs']=[{'variable':'goal_deadline','label':'How many monthly deposits will you make?'}]
        with TestClient(app) as client,patch.object(o,'call_json',return_value=main) as llm:
            response=client.post('/calculate',json=request())
        self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['status'],'needs_input')
        self.assertEqual(data['message'],'How many monthly deposits will you make?')
        self.assertEqual(data['verification']['status'],'input_sufficient')
        self.assertEqual(data['verification']['context'],'question')
        self.assertEqual(data['verification']['python_value'],1100)
        self.assertEqual(data['verification']['message'],'The independent check found enough information to calculate.')
        self.assertIsNone(data['answer']);self.assertEqual(llm.call_count,1)
        self.assertEqual(llm.call_args.kwargs['stage'],'main_calculation')

    def test_missing_report_without_repeated_target_uses_resolved_target(self):
        main={'missing_inputs':[{'variable':'goal_deadline','label':'How many monthly deposits will you make?'}]}
        with patch.object(o,'call_json',return_value=main) as llm,patch('gemini_gateway.call_json') as reroute:
            response=o.calculate(request())
        self.assertEqual(response['status'],'needs_input')
        self.assertEqual(response['verification']['status'],'input_sufficient')
        self.assertEqual(llm.call_count,1);reroute.assert_not_called()

    def test_main_missing_input_skipped_check_has_no_warning_or_inspector(self):
        req=request();req['extraction_meta']={}
        main={'missing_inputs':[{'variable':'goal_deadline','label':'How many monthly deposits will you make?'}]}
        with TestClient(app) as client,patch.object(o,'call_json',return_value=main) as llm,patch.object(o,'_verify') as verify:
            response=client.post('/calculate',json=req)
        self.assertEqual(response.status_code,200)
        data=response.json();self.assertEqual(data['status'],'needs_input')
        self.assertIsNone(data['verification']);verify.assert_not_called()
        self.assertEqual(llm.call_count,1)

    def test_cached_advisory_answer_retains_main_and_warning(self):
        response=self.call(1200).json()
        with TestClient(app) as client,patch.object(o,'call_json') as llm,patch.object(o,'_verify') as verifier:
            cached=client.post('/calculate',json=request()).json()
        llm.assert_not_called();verifier.assert_not_called()
        self.assertEqual(cached,response)


if __name__=='__main__':unittest.main()
