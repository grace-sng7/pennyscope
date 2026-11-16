import ts from 'typescript';
import fs from 'node:fs';
import path from 'node:path';
import Module, { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url),parent=new Module(fileURLToPath(import.meta.url));
function load(file){
 const m=new Module(file,parent);m.filename=file;m.paths=require.resolve.paths('typescript');
 const original=m.require.bind(m);
 m.require=id=>{if(id.endsWith('.css'))return {};const base=path.resolve(path.dirname(file),id);const candidate=[base+'.ts',base+'.tsx'].find(p=>fs.existsSync(p));return id.startsWith('.')&&candidate?load(candidate):original(id);};
 m._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,file);return m.exports;
}
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
const {fromCalculateWire}=load(path.resolve('lib/backend-wire.ts'));
const {AnswerCard}=load(path.resolve('components/chat-parts.tsx'));
const {VerificationWarning}=load(path.resolve('components/verification-warning.tsx'));
const extraction={assumptions:[],clarification_questions:[],goal_summary:'Savings projection',confidence_note:''};
const request={originalQuestion:'$350 plus six $125 deposits',extraction,edits:{},answers:{},parameters:{},answerFactBindings:{}};
for(const [main,status,icons] of [[1100,'matched',0],[1200,'mismatch',1],[1200,'unverified',1]]){
 const raw={status:'conditional',model:'savings_goal',target_variable:'projected_savings',
  answer:{headline:`Projected savings: $${main.toLocaleString('en-US')}.00`},
  factors:[{variable:'projected_savings',value:main,unit:'$',role:'derived',source:'inferred',source_detail:'Calculated by Main.'}],
  verification:{status,target_variable:'projected_savings',main_value:main,python_value:status==='unverified'?null:1100,unit:'$',message:status==='mismatch'?'The independent check differs. Main’s answer is shown.':'The independent check could not verify this answer. Main’s answer is shown.'}};
 const response=fromCalculateWire(raw,request);
 assert.equal(response.verification.status,status);
 const html=renderToStaticMarkup(React.createElement(AnswerCard,{response,interactive:false,params:{},onParam(){}}));
 assert.match(html,new RegExp(`\\$${main===1100?'1,100':'1,200'}\\.00`));
 assert.equal((html.match(/data-verification-warning=/g)??[]).length,icons);
 if(icons){assert.match(html,/role="img"/);assert.match(html,/title="/);assert.doesNotMatch(html,/\$1,100/);}
}
assert.equal(renderToStaticMarkup(React.createElement(VerificationWarning,{verification:{status:'matched'}})),'');
assert.throws(()=>fromCalculateWire({status:'conditional',answer:{headline:'A result'},verification:{status:'unknown'}},request));
console.log('PASS: Main $1,100 matched/no icon; Main $1,200 mismatch/one icon; unverifiable Main/one icon; no Python value replaces Main.');

const {QuestionText}=load(path.resolve('components/chat-parts.tsx'));
const question='How many monthly deposits will you make?';
for(const [status,icons] of [['unverified',0],['input_sufficient',1],[null,0]]){
 const raw={status:'needs_input',message:question,missing_inputs:[{variable:'goal_deadline',label:question}],
  ...(status?{verification:{status,context:'question',target_variable:'projected_savings',main_value:null,
   ...(status==='input_sufficient'?{python_value:1100,message:'The independent check found enough information to calculate.'}:{})}}:{})};
 const response=fromCalculateWire(raw,request);
 assert.equal(response.status,'needs_input');assert.equal(response.questions.length,1);
 assert.equal(response.questions[0].label,question);
 const html=renderToStaticMarkup(React.createElement(QuestionText,{text:response.questions[0].label,verification:response.verification}));
 assert.match(html,/How many monthly deposits will you make\?/);
 assert.equal((html.match(/data-verification-warning=/g)??[]).length,icons);
 const card=renderToStaticMarkup(React.createElement(AnswerCard,{response,interactive:false,params:{},onParam(){}}));
 assert.equal((card.match(/data-verification-warning=/g)??[]).length,icons);
 assert.doesNotMatch(card,/\$1,100/);
 if(icons)assert.match(html,/title="The independent check found enough information to calculate\."/);
}
console.log('PASS: Main question stays visible; unable/skipped check has no icon; sufficient check has exactly one icon with the specified message.');
