import ts from 'typescript';
import fs from 'node:fs';
import path from 'node:path';
import Module,{createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url),parent=new Module(fileURLToPath(import.meta.url));
function load(file){const m=new Module(file,parent);m.filename=file;m.paths=require.resolve.paths('typescript');const original=m.require.bind(m);m.require=id=>{if(id.endsWith('.css'))return {};const base=path.resolve(path.dirname(file),id),candidate=[base+'.ts',base+'.tsx'].find(p=>fs.existsSync(p));return id.startsWith('.')&&candidate?load(candidate):original(id);};m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,file);return m.exports;}
const React=require('react'),renderer=require('react-test-renderer');
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const {act}=renderer;
const {fromCalculateWire}=load(path.resolve('lib/backend-wire.ts'));
const {AnswerCard,AnswerSupporting,WorkingSheet}=load(path.resolve('components/chat-parts.tsx'));
const {PresentationBoundary}=load(path.resolve('components/presentation-boundary.tsx'));
const {readVisuals}=load(path.resolve('lib/answer-presentation.ts'));
const cases=JSON.parse(fs.readFileSync('tests/fixtures/grace-presentation.json','utf8'));
const text=tree=>JSON.stringify(tree.toJSON());
for(const fixture of cases.filter(c=>!c.name.endsWith('_followup'))){
 const extraction={...fixture.request.extraction_meta,assumptions:fixture.request.assumptions,clarification_questions:[],goal_summary:'Financial plan',confidence_note:''};
 const request={originalQuestion:fixture.request.original_question,extraction,edits:{},answers:{},parameters:{},answerFactBindings:{}};
 const response=fromCalculateWire(fixture.response,request);
 let tree;const previous=console.error;const selected=[];
 try{
  console.error=()=>{};
  await act(async()=>{tree=renderer.create(React.createElement(React.Fragment,null,
   React.createElement(AnswerCard,{response,interactive:true,params:{},onParam(){}}),
   React.createElement(AnswerSupporting,{response,interactive:true,disabled:false,onAsk:q=>selected.push(q)}),
   React.createElement(WorkingSheet,{extraction,math:response})))});
 }finally{console.error=previous;}
 assert.equal(tree.root.findAllByType('table').length,0);
 assert.match(text(tree),/Your options/);assert.match(text(tree),/Try a what-if/);
 const buttons=tree.root.findAllByType('button');
 const suggestion=buttons.find(b=>b.props.children===response.narrative.suggestions[0]);
 await act(async()=>suggestion.props.onClick());assert.equal(selected[0],response.narrative.suggestions[0]);
 const math=tree.root.findAllByType('button').find(b=>b.props.children==='Show the math');
 await act(async()=>math.props.onClick());assert.match(text(tree),/Hide the math/);
 if(fixture.name==='savings'){
  for(const title of ['Where the money comes from','Your month with this plan','Month by month'])assert.match(text(tree),new RegExp(title));
  const monthly=tree.root.findAllByType('button').find(b=>b.props.children==='Show monthly details');
  await act(async()=>monthly.props.onClick());assert.match(text(tree),/Dec 26/);assert.match(text(tree),/Jul 27/);
  const columns=tree.root.findAll(n=>typeof n.props?.onMouseEnter==='function');
  await act(async()=>columns[0].props.onMouseEnter());assert.match(text(tree),/350/);
 }else{assert.match(text(tree),/available after current expenses/);assert.match(text(tree),/Your month with the new cost/);assert.doesNotMatch(text(tree),/Month by month/);}
 await act(async()=>tree.unmount());
 const raw=structuredClone(fixture.response);raw.visuals={kind:'one_time',timeline:'bad',budget:{income:1}};
 const degraded=fromCalculateWire(raw,request);assert.equal(degraded.answer.headline,response.answer.headline);assert.equal(degraded.visuals,undefined);assert.equal(degraded.narrative.text,response.narrative.text);
 const mismatch=fromCalculateWire({...fixture.response,verification:{...fixture.response.verification,status:'mismatch'}},request);assert.equal(mismatch.visuals,undefined);assert.equal(mismatch.answer.headline,response.answer.headline);
}
assert.equal(readVisuals({kind:'recurring',budget_now:{income:100,expenses:[],goal:20,left_over:900}}),undefined);
function BrokenSupporting(){throw new Error('Forced optional chart error');}
let tree;const previous=console.error;
try{
 console.error=()=>{};
 const fixture=cases[0];const extraction={assumptions:fixture.request.assumptions,clarification_questions:[],goal_summary:'',confidence_note:''};
 const response=fromCalculateWire(fixture.response,{originalQuestion:'Savings',extraction,edits:{},answers:{},parameters:{},answerFactBindings:{}});
 await act(async()=>{tree=renderer.create(React.createElement(React.Fragment,null,React.createElement(AnswerCard,{response,interactive:false,params:{},onParam(){}}),React.createElement(PresentationBoundary,{fallback:null},React.createElement(BrokenSupporting))))});
 assert.match(text(tree),/Affordability status: Yes/);
}finally{console.error=previous;if(tree)await act(async()=>tree.unmount());}
console.log('PASS: Grace funding/budget/timeline/options, exact legends, month details, hover, math and suggested questions; no tables; optional failures preserve the answer.');
// Click the actual suggested-question controls through ChatApp and verify that
// they submit corrections and recalculate using the existing transport flow.
process.env.NEXT_PUBLIC_BACKEND_MODE='live';
const ChatApp=load(path.resolve('components/chat-app.tsx')).default;
for(const name of ['savings','budget']){
 const fixture=cases.find(c=>c.name===name),followup=cases.find(c=>c.name===name+'_followup');
 const ex=f=>({...f.request.extraction_meta,assumptions:f.request.assumptions,clarification_questions:[],goal_summary:'Supported plan',confidence_note:''});
 const originalFetch=globalThis.fetch;const actions=[];let count=0;let posted;
 globalThis.fetch=async(url,init)=>{
  const action=url.split('/').at(-1);actions.push(action);
  if(action==='extract')return {ok:true,json:async()=>ex(fixture)};
  if(action==='correct'){posted=JSON.parse(init.body);return {ok:true,json:async()=>ex(followup)};}
  assert.equal(action,'calculate');count++;return {ok:true,json:async()=>count===1?fixture.response:followup.response};
 };
 let tree;const previous=console.error;
 try{
  console.error=()=>{};await act(async()=>{tree=renderer.create(React.createElement(ChatApp))});console.error=previous;
  await act(async()=>tree.root.findByType('textarea').props.onChange({target:{value:fixture.request.original_question}}));
  await act(async()=>tree.root.findByType('form').props.onSubmit({preventDefault(){}}));
  const suggestion=fixture.response.narrative.suggestions[0];
  const button=tree.root.findAllByType('button').find(b=>b.props.children===suggestion);
  assert.ok(button);assert.equal(button.props.disabled,false);
  await act(async()=>button.props.onClick());
  assert.deepEqual(actions,['extract','calculate','correct','calculate']);assert.equal(posted.user_correction,suggestion);
  const answerCards=tree.root.findAll(n=>typeof n.type==='function'&&n.type.name==='AnswerCard');
  assert.equal(answerCards.length,2);assert.equal(answerCards[1].props.response.answer.headline,followup.response.answer.headline);
 }finally{console.error=previous;globalThis.fetch=originalFetch;if(tree)await act(async()=>tree.unmount());}
}
console.log('PASS: savings and budget suggested-question clicks perform correction -> calculation and render the updated answer through real ChatApp handlers.');
// Exercise the actual optional visual component's own boundary, not just a
// stand-in throwing component: narrative and core answer must remain visible.
{
 const fixture=cases[0];const extraction={assumptions:fixture.request.assumptions,clarification_questions:[],goal_summary:'',confidence_note:''};
 const response=fromCalculateWire(fixture.response,{originalQuestion:'Savings',extraction,edits:{},answers:{},parameters:{},answerFactBindings:{}});
 response.visuals={kind:'one_time',options:null};
 let tree;const previous=console.error;
 try{
  console.error=()=>{};
  await act(async()=>{tree=renderer.create(React.createElement(React.Fragment,null,React.createElement(AnswerCard,{response,interactive:false,params:{},onParam(){}}),React.createElement(AnswerSupporting,{response,interactive:true,disabled:false,onAsk(){}})))});
  assert.match(text(tree),/Affordability status: Yes/);assert.match(text(tree),/You are starting with/);assert.match(text(tree),/Try a what-if/);
 }finally{console.error=previous;if(tree)await act(async()=>tree.unmount());}
}
console.log('PASS: a forced exception in the real Grace visual component leaves Main, narrative, math and suggestions visible.');
