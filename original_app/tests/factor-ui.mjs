import ts from 'typescript';
import fs from 'node:fs';
import path from 'node:path';
import Module, { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url), parent=new Module(fileURLToPath(import.meta.url));
function load(file) {
  const m=new Module(file,parent);m.filename=file;m.paths=require.resolve.paths('typescript');
  const original=m.require.bind(m);
  m.require=id=>{if(id.endsWith('.css'))return {};const base=path.resolve(path.dirname(file),id);const candidate=[base+'.ts',base+'.tsx'].find(p=>fs.existsSync(p));return id.startsWith('.')&&candidate?load(candidate):original(id);};
  m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,file);return m.exports;
}
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
const render=context=>renderToStaticMarkup(React.createElement(ui.ModelResultDetails,{context}));
const factors=load(path.resolve('lib/model-factors.ts'));
const ui=load(path.resolve('components/model-result-details.tsx'));
const wire=load(path.resolve('lib/backend-wire.ts'));
const presentation=load(path.resolve('lib/presentation-model.ts'));
const contract=load(path.resolve('lib/calculation-contract.ts'));
const f=(variable,value,role='known',unit='$',extra={})=>({variable,value,unit,role,source:role==='known'?'stated':role==='derived'?'inferred':'missing',source_detail:'Evidence',...extra});
const context=(target,items,model='savings_goal')=>({model,target_variable:target,factors:items});

// The same factor changes roles, and all savings targets use the same renderer/model.
for(const target of ['affordability_status','required_monthly_savings','projected_savings','months_to_goal']){
  const c=context(target,[f('current_savings',500),f(target,target==='affordability_status'?'Yes':250,'derived','text')]);
  assert.doesNotMatch(render(c),/Solving for|I Worked Out/);
  assert.match(render(c),/Current savings/);assert.equal(c.model,'savings_goal');
}
const known=f('monthly_contribution',250), derived=f('monthly_contribution',250,'derived');
assert.equal(factors.factorGroups([known])[0].title,'You Told Me');
assert.equal(factors.factorGroups([derived])[0].title,'I Worked Out');
assert.equal(factors.factorGroups([f('apr',null,'missing','%')])[0].title,'Still Unknown');
const estimate=f('monthly_contribution',250,'known','$/month',{source:'inferred'});
assert.equal(factors.factorGroups([estimate])[0].title,'You Told Me');
assert.equal(factors.validateModelContext(context('monthly_contribution',[estimate])).factors[0].source,'inferred');
assert.doesNotMatch(render(context('projected_savings',[f('projected_savings',1000,'derived'),f('irrelevant_secret',20,'known','$',{relevant:false})])),/Irrelevant secret/);

// Optional wire extension survives adapters; legacy responses still validate.
const extraction={assumptions:[{variable:'monthly_contribution',value:250,unit:'$/month',source:'stated',source_detail:'User said 250'}],clarification_questions:[{target_variable:'months_to_goal',question:'Old target question',why_it_matters:'legacy'},{target_variable:'apr',question:'Irrelevant APR',why_it_matters:'legacy'}],goal_summary:'Time to goal',confidence_note:'Test'};
const request={originalQuestion:'How long?',extraction,edits:{},answers:{},parameters:{},answerFactBindings:{}};
const c=context('months_to_goal',[f('monthly_contribution',250),f('months_to_goal',5,'derived','months')]);
const response=wire.fromCalculateWire({status:'conditional',answer:{headline:'Five months'},...c},request);
assert.equal(response.target_variable,'months_to_goal');assert.equal(response.factors.length,2);
const displayed=presentation.presentResponse(extraction,response);
assert.equal(displayed.questions.length,0,'Neither a solved target nor irrelevant factors become questions');
assert.equal(displayed.information.find(i=>i.id==='model-months_to_goal'),undefined);
contract.validateCalculation(displayed,extraction);
const legacy=wire.fromCalculateWire({status:'ready',answer:{headline:'Legacy result'},metrics:[{label:'Old metric',value:'$20'}]},request);
assert.equal(legacy.factors,undefined);contract.validateCalculation(legacy,extraction);

// Structured factors keep arbitrary row counts and escaped user content.
const bills=context('amounts_owed',[f('participants',JSON.stringify(['A','B','C','D','E']),'known','text'),f('items',JSON.stringify([{name:'<script>bad</script>',amount:30,shared_by:['A','B']},{name:'Dinner',amount:90,shared_by:['C','D','E']}]),'known','text'),f('settlements',JSON.stringify([{from:'B',to:'A',amount:'30.00'},{from:'C',to:'A',amount:'30.00'}]),'derived','text')],'bill_split');
const html=render(bills);assert.match(html,/Dinner/);assert.match(html,/30.00/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
const budget=render(context('projected_surplus',[f('expense_categories',JSON.stringify([{name:'Rent',amount:1000},{name:'Dining',amount:500}]),'known','text'),f('expense_adjustments',JSON.stringify([{name:'Dining',proposed_reduction:100}]),'known','text'),f('projected_surplus',600,'derived','$/month')],'budget_cash_flow'));
assert.match(budget,/Rent/);assert.match(budget,/Proposed reduction/);
for(const target of ['estimated_payoff_months','required_monthly_payment'])assert.doesNotMatch(render(context(target,[f(target,10,'derived')],'debt_repayment')),/Solving for|I Worked Out/);

for(const bad of [context('x',[f('x',1),f('x',2)]),context('absent',[f('x',1)]),context('x',[f('x',null,'known')]),context('x',[f('x',1,'output')]),context('x',[f('x',1,'derived','$',{relevant:false})])])assert.throws(()=>factors.validateModelContext(bad));
assert.throws(()=>wire.fromCalculateWire({status:'ready',answer:{headline:'bad'},...context('x',[f('x',null,'known')])},request));
console.log('PASS: dynamic roles, four savings targets, optional schema, structured budgets/bills/debt, relevance, escaped content, and legacy compatibility');
const extractionContract=load(path.resolve('lib/extraction.ts'));
const estimatedRaw={...extraction,assumptions:[{variable:estimate.variable,value:estimate.value,unit:estimate.unit,source:estimate.source,source_detail:estimate.source_detail}],...context('monthly_contribution',[estimate])};
assert.equal(extractionContract.validateExtraction(estimatedRaw).factors[0].role,'known');
assert.throws(()=>extractionContract.validateExtraction({...estimatedRaw,factors:[{...estimate,value:999}]}));

// Exercise every currently supported target from the actual Python registry.
const {execFileSync}=require('node:child_process');
const registries=JSON.parse(execFileSync('../.venv/bin/python',['-c',
  'import sys,json;sys.path.insert(0,"backend_reference");from factor_registry import REGISTRIES;print(json.dumps({k:list(v.targets) for k,v in REGISTRIES.items()}))'
],{encoding:'utf8'}));
const chat=load(path.resolve('components/chat-parts.tsx'));
const renderComponent=(component,props)=>renderToStaticMarkup(React.createElement(component,props));
let targetChecks=0;
for(const [model,targets] of Object.entries(registries))for(const target of targets){
  const items=[f('provided_input',100),f('needed_input',null,'missing'),f(target,null,'missing')];
  const raw={...context(target,items,model),assumptions:items.map(({variable,value,unit,source,source_detail})=>({variable,value,unit,source,source_detail})),
    goal_summary:'Review supplied values',confidence_note:'',
    clarification_questions:[{target_variable:target,question:'Do not ask for the target',why_it_matters:''},{target_variable:'needed_input',question:'Please provide missing input',why_it_matters:''}]};
  const before=structuredClone(raw);
  assert.equal(factors.factorGroups([f(target,null,'missing')],target).length,0,'A target alone must not create a Still Unknown section');
  const understood=renderComponent(chat.Understood,{extraction:raw,onPick:()=>{}});
  assert.match(understood,/You Told Me/i);assert.match(understood,/Still Unknown/i);
  assert.match(understood,/Provided input/);assert.match(understood,/Needed input/);
  const targetLabel=load(path.resolve('lib/workspace-model.ts')).label(target);
  assert.ok(!understood.includes(targetLabel),model+': '+target+' is not a review chip');
  const sheet=renderComponent(chat.WorkingSheet,{extraction:raw,math:null});
  assert.ok(!sheet.includes(targetLabel));assert.match(sheet,/Needed input/);
  const request={originalQuestion:'Question',extraction:raw,edits:{},answers:{},parameters:{},answerFactBindings:{}};
  const pending=wire.fromCalculateWire({status:'needs_input',message:'Need input',
    missing_inputs:[{variable:target},{variable:'needed_input'}],...context(target,items,model)},request);
  assert.equal(pending.questions.length,1);assert.equal(pending.questions[0].binding.index,1);
  const view=presentation.presentResponse(raw,pending);
  assert.ok(view.information.every(field=>field.label!==targetLabel));
  assert.ok(view.questions.every(q=>q.label!=='Do not ask for the target'));
  const solvedItems=items.map(item=>item.variable===target?f(target,250,'derived'):item);
  const solved=wire.fromCalculateWire({status:'ready',answer:{headline:'The calculated answer is 250.'},...context(target,solvedItems,model)},request);
  const answer=renderComponent(chat.AnswerCard,{response:solved,interactive:true,params:{},onParam:()=>{}});
  assert.match(answer,/The calculated answer is 250/);
  assert.ok(!answer.includes(targetLabel));assert.doesNotMatch(answer,/<input/);
  assert.equal(solved.target_variable,target);assert.equal(solved.factors.find(f=>f.variable===target).value,250);
  assert.deepEqual(raw,before,'Display filtering must not mutate backend state');
  targetChecks++;
}
assert.equal(Object.keys(registries).length,4);
console.log('PASS: target stays in state and response text, excluded from chips, working sheet, missing questions and result controls for '+targetChecks+' supported targets');
