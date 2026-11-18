import ts from 'typescript';
import fs from 'node:fs';
import path from 'node:path';
import Module,{createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url),parent=new Module(fileURLToPath(import.meta.url));
function load(file){const m=new Module(file,parent);m.filename=file;m.paths=require.resolve.paths('typescript');const original=m.require.bind(m);m.require=id=>{if(id.endsWith('.css')){const css=fs.readFileSync(path.resolve(path.dirname(file),id),'utf8');return Object.fromEntries([...css.matchAll(/\.([A-Za-z_][\w-]*)/g)].map(x=>[x[1],x[1]]));}const base=path.resolve(path.dirname(file),id),candidate=[base+'.ts',base+'.tsx'].find(p=>fs.existsSync(p));return id.startsWith('.')&&candidate?load(candidate):original(id);};m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,file);return m.exports;}
const React=require('react'),renderer=require('react-test-renderer');
globalThis.IS_REACT_ACT_ENVIRONMENT=true;
const {act}=renderer;
const {fromCalculateWire}=load(path.resolve('lib/backend-wire.ts'));
const {Understood,AnswerCard,AnswerSupporting,WorkingSheet}=load(path.resolve('components/chat-parts.tsx'));
const {factText,factLabel}=load(path.resolve('lib/fact-presentation.ts'));
assert.equal(factLabel('contribution_entries'),'Deposit schedule');
assert.equal(factText(0,'months','goal_deadline'),'Today');
const schedule=JSON.stringify([{amount:60,frequency:'weekly',count:8}]);
assert.equal(factText(schedule,'text','contribution_entries'),'$60 · every week · 8 deposits');
assert.match(factText('[{"name":"rent","amount":1000,"frequency":"monthly"}]'),/rent: \$1,000 · every month/);
assert.match(factText('[{"name":"pizza","amount":30,"shared_by":["Nina","Leo","me"]}]'),/pizza: \$30 · shared by Nina, Leo, me/);
const data=JSON.parse(fs.readFileSync('tests/fixtures/deposit-presentation.json','utf8'));
const facts=data.request.assumptions.map(a=>({...a,unit:a.variable==='current_savings'?'$':'text',source:'stated',source_detail:'User supplied fact',role:'known'}));
const ex={model:'savings_goal',target_variable:'projected_savings',goal_summary:'Savings after eight weekly deposits',confidence_note:'',assumptions:facts,clarification_questions:[],factors:[...facts,{variable:'projected_savings',value:null,unit:'$',role:'missing',source:'missing',source_detail:'Requested result'}]};
const req={originalQuestion:data.request.original_question,extraction:ex,edits:{},answers:{},parameters:{},answerFactBindings:{}};
const response=fromCalculateWire(data.calculation,req);
const today=JSON.parse(fs.readFileSync('tests/fixtures/today-purchase.json','utf8'));
const todayResponse=fromCalculateWire(today.calculation,{...req,extraction:today.extraction});
const noop=()=>{};
function scene(extraction,result){return React.createElement('div',{className:'page'},React.createElement('header',{className:'header'},'Pennyscope · Presentation regression preview'),React.createElement('div',{className:'body'},React.createElement('main',{className:'thread'},React.createElement('div',{className:'bubble'},React.createElement(Understood,{extraction,onPick:noop})),React.createElement('div',{className:'bubble'},React.createElement(AnswerCard,{response:result,interactive:true,params:{},onParam:noop})),React.createElement(AnswerSupporting,{response:result,interactive:true,disabled:false,onAsk:noop})),React.createElement('div',{className:'sheetWrap'},React.createElement(WorkingSheet,{extraction,math:result}))));}
for(const [extraction,result] of [[ex,response],[today.extraction,todayResponse]]){
 let tree;const old=console.error;console.error=()=>{};
 try{await act(async()=>{tree=renderer.create(scene(extraction,result));});}finally{console.error=old;}
 const answer=tree.root.find(n=>typeof n.type==='function'&&n.type.name==='AnswerCard');
 const explanation=answer.findAll(n=>n.type==='p'&&String(n.props.className).includes('answerExplanation'));
 assert.equal(explanation.length,1,'the explanation stays inside the answer card');
 assert.equal(explanation[0].props.children,result.narrative.text);
 const support=tree.root.find(n=>typeof n.type==='function'&&n.type.name==='AnswerSupporting');
 assert.equal(support.findAll(n=>n.type==='p'&&n.props.children===result.narrative.text).length,0,'no duplicated floating explanation');
 const output=JSON.stringify(tree.toJSON());assert.doesNotMatch(output,/Contribution entries|1 entries/);assert.equal(tree.root.findAllByType('table').length,0);
 if(result===response){assert.match(output,/every week/);assert.match(output,/8 deposits/);assert.match(output,/Savings timeline/);assert.match(output,/580/);assert.match(output,/480/);assert.equal(tree.root.findAll(n=>n.props?.['data-verification-warning']==='unverified').length,1);}
 else{assert.match(output,/Today/);assert.match(output,/150/);assert.match(output,/Where the money comes from/);assert.doesNotMatch(output,/Affordability status:/);}
 await act(async()=>tree.unmount());
}
if(process.env.PS_PREVIEW){
 const server=require('react-dom/server');const css=fs.readFileSync('app/globals.css','utf8')+'\n'+fs.readFileSync('app/chat/chat.module.css','utf8');fs.mkdirSync(process.env.PS_PREVIEW,{recursive:true});
 for(const [name,extraction,result] of [['weekly',ex,response],['today',today.extraction,todayResponse]])fs.writeFileSync(path.join(process.env.PS_PREVIEW,name+'.html'),'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'</style>'+server.renderToStaticMarkup(scene(extraction,result)));
}
console.log('PASS: deposit amount/frequency/count, Today, funding, narrative, weekly timeline and readable worksheet; no raw entry labels or tables.');
