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
process.env.NEXT_PUBLIC_BACKEND_MODE='live';
const ChatApp=load(path.resolve('components/chat-app.tsx')).default;
const fixture=JSON.parse(fs.readFileSync(process.env.PS_LIVE_AUDIT_FIXTURE??'tests/regression_artifacts/backend_live_audit.json','utf8'));
const real=fixture.after.runs[0],actions=[];const originalFetch=globalThis.fetch,originalError=console.error;
globalThis.fetch=async(url,options)=>{
 const action=url.split('/').at(-1);actions.push(action);
 assert.ok(['extract','calculate'].includes(action));
 if(action==='calculate'){
  const req=JSON.parse(options.body);assert.equal(req.extraction_meta.model,'savings_goal');
  assert.equal(req.assumptions.find(a=>a.variable==='current_savings').value,900);
 }
 return {ok:true,json:async()=>structuredClone(action==='extract'?real.extraction:real.calculation)};
};
let tree;
try{
 console.error=()=>{};
 await act(async()=>{tree=renderer.create(React.createElement(ChatApp));});
 await act(async()=>tree.root.findByType('textarea').props.onChange({target:{value:fixture.after.request.user_message}}));
 await act(async()=>tree.root.findByType('form').props.onSubmit({preventDefault(){}}));
 assert.deepEqual(actions,['extract','calculate']);
 const out=JSON.stringify(tree.toJSON());
 for(const amount of ['2,400','1,000','600','900','2,500','1,600','800','4,100'])assert.ok(out.includes(amount),amount+' survives the actual UI adapter/render');
 assert.match(out,/next March/);assert.match(out,/Month by month/i);
 assert.doesNotMatch(out,/Still unknown/i);assert.doesNotMatch(out,/650/);
 assert.equal(tree.root.findAll(n=>typeof n.type==='function'&&n.type.name==='AnswerCard').length,1);
 assert.equal(tree.root.findAll(n=>n.props?.['data-verification-warning']).length,0);
 assert.equal(tree.root.findAllByType('table').length,0);
}finally{
 globalThis.fetch=originalFetch;console.error=originalError;if(tree)await act(async()=>tree.unmount());
}
console.log('PASS: recorded real Bedrock extraction/calculation survives the actual ChatApp, adapter, worksheet, funding/budget/timeline/narrative; no missing facts, follow-up, inverse calculation, or warning.');
