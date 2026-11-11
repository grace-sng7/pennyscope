import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend_reference'))
import dynamic_models as d
import orchestration as o
from contract import CalculateResponse


def factor(name,value,role='known',unit='$'):
    if isinstance(value,(list,dict)):value=json.dumps(value)
    return dict(variable=name,value=value,unit=unit,role=role,
                source='missing' if role=='missing' else 'stated' if role=='known' else 'inferred',source_detail='Fictional test evidence',relevant=True)


def scenario(model,inputs,target,output_unit='$',bindings=None):
    bindings=bindings or {k:k for k in inputs if k!='solve_for'}
    factors=[factor(bindings[k],v,unit='months' if k in ('months','payoff_months') else '$/month' if k in ('monthly_savings','monthly_income','monthly_spending','monthly_payment') else '$') for k,v in inputs.items() if k in bindings]
    factors=[f for i,f in enumerate(factors) if f['variable'] not in [x['variable'] for x in factors[:i]]]
    factors=[f for f in factors if f['variable']!=target]+[factor(target,0,'derived',output_unit)]
    draft={'model':model,'inputs':inputs,'bindings':bindings,'target_variable':target,'factors':factors,'results':{},'headline':'Primary draft','calculation':'Primary calculation'}
    facts={f['variable']:{'value':f['value'],'unit':f['unit'],'source':f['source'],'source_detail':f['source_detail']} for f in factors if f['role']=='known'}
    return draft,facts


class DynamicModels(unittest.TestCase):
    def run_scenario(self,model,inputs,target,unit='$',bindings=None):
        draft,facts=scenario(model,inputs,target,unit,bindings)
        d.validate(draft,facts);actual=d.verify(draft)
        result=d.present(draft,actual,{'detail':'Reviewed scenario','assumptions':[]},facts)
        CalculateResponse.model_validate(result)
        self.assertFalse(result['parameters'])
        return next(f for f in result['factors'] if f['variable']==target)['value'],result

    def test_same_savings_model_four_targets(self):
        cases=[('future_balance',dict(current_savings=500,monthly_savings=200,months=4),'projected_savings',1300,'$'),
               ('affordability',dict(current_savings=500,monthly_savings=200,months=4,target=1500),'affordability_status','No','text'),
               ('monthly_required',dict(current_savings=500,months=4,target=1500),'required_monthly_savings',250,'$/month'),
               ('months_required',dict(current_savings=500,monthly_savings=200,target=1500),'months_to_goal',5,'months')]
        for mode,inputs,target,expected,unit in cases:
            value,result=self.run_scenario('savings_goal',{'solve_for':mode,**inputs},target,unit)
            self.assertEqual(value,expected);self.assertEqual(result['model'],'savings_goal')

    def test_contribution_is_target_then_known_with_same_variable_name(self):
        value,result=self.run_scenario('savings_goal',dict(solve_for='monthly_required',current_savings=500,months=4,target=1500),'monthly_contribution','$/month')
        self.assertEqual(value,250)
        _,other=self.run_scenario('savings_goal',dict(solve_for='future_balance',current_savings=500,monthly_savings=250,months=4),'projected_savings',bindings={'current_savings':'current_savings','monthly_savings':'monthly_contribution','months':'goal_deadline'})
        self.assertEqual(next(f['role'] for f in other['factors'] if f['variable']=='monthly_contribution'),'known')
        self.assertEqual(next(f['role'] for f in result['factors'] if f['variable']=='monthly_contribution'),'derived')

    def test_debt_both_directions_and_total(self):
        self.assertEqual(self.run_scenario('debt_repayment',dict(balance=1000,apr=0,monthly_payment=100),'estimated_payoff_months','months')[0],10)
        self.assertEqual(self.run_scenario('debt_repayment',dict(balance=1000,apr=0,payoff_months=10),'required_monthly_payment','$/month')[0],100)
        self.assertEqual(self.run_scenario('debt_repayment',dict(balance=1000,apr=0,payoff_months=10),'total_repayment')[0],1000)

    def test_budget_breakdown_and_adjustments(self):
        categories=[{'name':'Rent','amount':1000,'flexibility':'essential'},{'name':'Dining','amount':500,'flexibility':'discretionary'}]
        inputs=dict(monthly_income=2000,monthly_spending=1500,expense_categories=categories,expense_adjustments=[{'name':'Dining','proposed_reduction':100}])
        value,_=self.run_scenario('budget_cash_flow',inputs,'projected_surplus','$/month')
        self.assertEqual(value,600)

    def test_variable_participants_and_settlement(self):
        inputs=dict(method='equal',people=['A','B','C','D'],total=120,amounts_paid={'A':120,'B':0,'C':0,'D':0})
        value,result=self.run_scenario('bill_split',inputs,'settlements','text')
        self.assertEqual(len(json.loads(value)),3)
        self.assertEqual(sum(float(t['amount']) for t in json.loads(value)),90)

    def test_custom_and_shared_items(self):
        value,_=self.run_scenario('bill_custom',dict(total=120,weights={'A':2,'B':1}),'amounts_owed','text')
        self.assertEqual(json.loads(value),{'A':'80.00','B':'40.00'})
        value,_=self.run_scenario('bill_split',dict(method='itemized',people=['A','B'],items=[{'amount':20,'shared_by':['A']}],shared_items=[{'amount':40,'shared_by':['A','B']}]),'amounts_owed','text')
        self.assertEqual(json.loads(value),{'A':'40.00','B':'20.00'})

    def test_no_implicit_zero_or_invented_facts(self):
        draft,facts=scenario('savings_goal',dict(solve_for='monthly_required',months=4,target=1500),'monthly_contribution')
        with self.assertRaises(ValueError):d.validate(draft,facts)
        draft,facts=scenario('savings_goal',dict(solve_for='future_balance',current_savings=500,monthly_savings=200,months=4),'projected_savings')
        draft['inputs']['monthly_savings']=999
        with self.assertRaises(ValueError):d.validate(draft,facts)

    def test_llm_draft_is_verified_inspected_and_formatted(self):
        o.CACHE.clear();o.PENDING_REVIEWS.clear()
        draft,facts=scenario('savings_goal',dict(solve_for='monthly_required',current_savings=500,months=4,target=1500),'monthly_contribution','$/month')
        req={'original_question':'How much must I save monthly?','assumptions':[dict(variable=k,**v) for k,v in facts.items()],'extra_inputs':{},'answers':[],'parameters':{},'extraction_meta':{}}
        with patch.object(o,'call_json',side_effect=[draft,{'decision':'approved','headline':'The required saving is verified.','detail':'Reviewed','assumptions':[]}]) as llm:
            result=o.calculate(req)
        self.assertEqual(llm.call_count,2)
        self.assertEqual(result['target_variable'],'monthly_contribution')
        self.assertIn('250.00',result['answer']['headline'])
        self.assertFalse(result['parameters'])

class FactorEnvelope(unittest.TestCase):
    def test_known_estimate_keeps_source_and_rejects_conflicting_display(self):
        from contract import ExtractionResponse
        f=factor('monthly_contribution',200,'known','$/month');f['source']='inferred'
        raw={'assumptions':[{k:v for k,v in f.items() if k in ('variable','value','unit','source','source_detail')}],
             'clarification_questions':[],'goal_summary':'Test','confidence_note':'Estimate',
             'model':'savings_goal','target_variable':'monthly_contribution','factors':[f]}
        self.assertEqual(ExtractionResponse.model_validate(raw).model_extra['factors'][0]['source'],'inferred')
        raw['factors'][0]['value']=999
        with self.assertRaises(ValueError):ExtractionResponse.model_validate(raw)
