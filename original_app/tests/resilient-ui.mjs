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
const {PresentationBoundary,PlainResult}=load(path.resolve('components/presentation-boundary.tsx'));
const {WorkingSheet}=load(path.resolve('components/chat-parts.tsx'));
const {HttpCalculationService}=load(path.resolve('lib/http-services.ts'));
const plain=load(path.resolve('lib/plain-chat.ts'));
const headline='Nina owes $24, Leo owes $24, and you owe $12.';
const response={status:'conditional',answer:{headline},verification:{status:'unverified',target_variable:'amounts_owed',main_value:{Nina:24,Leo:24,me:12}},factors:[{bad:'card metadata'}]};
const extraction={assumptions:[{variable:'participants',value:'["Nina","Leo","me"]',unit:'text',source:'stated',source_detail:'User supplied names'}],clarification_questions:[],goal_summary:'Split the meal',confidence_note:''};
const request={originalQuestion:'Shared pizza and separate items',extraction,edits:{},answers:{},parameters:{},answerFactBindings:{}};
let calls=0;
const service=new HttpCalculationService(async()=>{calls++;return {ok:true,json:async()=>response};});
const converted=await service.calculate(request);
assert.equal(calls,1);assert.equal(converted.chat_fallback.text,headline);
assert.equal(converted.verification.status,'unverified');
assert.equal(extraction.assumptions[0].value,'["Nina","Leo","me"]');

function BrokenCard(){throw new Error('Forced card rendering failure');}
let tree;
const previousError=console.error;
try{
 console.error=()=>{}; // The error boundary intentionally catches this test error.
 await act(async()=>{tree=renderer.create(React.createElement(React.Fragment,null,
  React.createElement(PresentationBoundary,{fallback:React.createElement(PlainResult,{response}),resetKey:response},React.createElement(BrokenCard)),
  React.createElement(WorkingSheet,{extraction,math:null})))});
}finally{console.error=previousError;}
const output=JSON.stringify(tree.toJSON());
assert.match(output,/Nina owes \$24, Leo owes \$24, and you owe \$12/);
assert.equal(tree.root.findAll(node=>node.props?.['data-verification-warning']==='unverified').length,1);
assert.equal(tree.root.findAll(node=>node.props?.['aria-label']==='Working sheet').length,1);
assert.match(output,/Nina/);assert.match(output,/participants/i);
await act(async()=>tree.unmount());
assert.equal(plain.parsePlainChat({kind:'question',text:'Who had the salad?'}).kind,'question');
console.log('PASS: forced adapter/card failures retain Main text and advisory icon; confirmed worksheet data remains rendered without a new LLM call.');

// Gap corrections must calculate even though no registered assumptions changed.
process.env.NEXT_PUBLIC_BACKEND_MODE='live';
const ChatApp=load(path.resolve('components/chat-app.tsx')).default;
const gap={assumptions:[],clarification_questions:[],goal_summary:'Work through the timing.',confidence_note:'',model:null,target_variable:null,factors:[],routing:{model:'gap'}};
const factor=(variable,value,role,unit='$')=>({variable,value,unit,role,source:role==='known'?'stated':'inferred',source_detail:'User facts and Main calculation.'});
let calculations=0;const actions=[];const previousFetch=globalThis.fetch;
globalThis.fetch=async(url)=>{
 const action=url.split('/').at(-1);actions.push(action);
 if(action==='extract'||action==='correct')return {ok:true,json:async()=>gap};
 assert.equal(action,'calculate');calculations++;
 const amount=calculations===1?80:0;
 return {ok:true,json:async()=>({status:'conditional',model:null,target_variable:'cash_needed',answer:{headline:`You need $${amount} before the bill is due.`},
  factors:[factor('checking',220,'known'),factor('bill',300,'known'),factor('cash_at_due_date',calculations===1?220:370,'derived'),factor('cash_needed',amount,'derived')],
  verification:{status:'unverified',target_variable:'cash_needed',main_value:amount,unit:'$'}})};
};
let chatTree;
try{
 console.error=()=>{};
 await act(async()=>{chatTree=renderer.create(React.createElement(ChatApp));});
 console.error=previousError;
 for(const message of ['I have $220, a $300 bill on the 4th and a $150 paycheck on the 6th.','Move the paycheck to the 3rd.']){
  await act(async()=>chatTree.root.findByType('textarea').props.onChange({target:{value:message}}));
  await act(async()=>chatTree.root.findByType('form').props.onSubmit({preventDefault(){}}));
 }
 assert.deepEqual(actions,['extract','calculate','correct','calculate']);
 const cards=chatTree.root.findAll(node=>typeof node.type==='function'&&node.type.name==='AnswerCard');
 assert.equal(cards.length,2);
 assert.match(cards[0].findByType('p').props.children[0],/You need \$80/);
 assert.match(cards[1].findByType('p').props.children[0],/You need \$0/);
 for(const card of cards)assert.equal(card.findAll(node=>node.props?.['data-verification-warning']==='unverified').length,1);
 assert.match(JSON.stringify(chatTree.toJSON()),/370/);
 assert.match(JSON.stringify(chatTree.toJSON()),/Cash at due date/);
}finally{
 console.error=previousError;globalThis.fetch=previousFetch;
 if(chatTree)await act(async()=>chatTree.unmount());
}
console.log('PASS: actual chat handlers render scoped $80 then corrected $0 cards with one warning each and update derived worksheet values.');
