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
const fixture=JSON.parse(fs.readFileSync('tests/fixtures/clarification-first.json','utf8'));
const oldFetch=globalThis.fetch,oldError=console.error;
const actions=[];
globalThis.fetch=async url=>{actions.push(url.split('/').at(-1));assert.equal(actions.at(-1),'extract');return {ok:true,json:async()=>structuredClone(fixture)};};
{
 let tree;
 try{
  console.error=()=>{};
  await act(async()=>{tree=renderer.create(React.createElement(ChatApp));});
  assert.equal(tree.root.findAll(n=>n.props.role==='radiogroup'||n.props.role==='radio').length,0);
  await act(async()=>tree.root.findByType('textarea').props.onChange({target:{value:'A trip may cost $3000; I earn $200 a month.'}}));
  await act(async()=>tree.root.findByType('form').props.onSubmit({preventDefault(){}}));
  let output=JSON.stringify(tree.toJSON());
  assert.match(output,/Still unknown/i);assert.match(output,/Monthly income/i);
  assert.equal(tree.root.findAll(n=>typeof n.type==='function'&&n.type.name==='AnswerCard').length,0);
  for(let i=0;i<3;i++){
   const skip=tree.root.findAllByType('button').find(n=>n.props.children==='Not sure, skip this');assert.ok(skip);
   await act(async()=>skip.props.onClick());
  }
  output=JSON.stringify(tree.toJSON());
  assert.match(output,/unknown/i);assert.doesNotMatch(output,/\$1,000/);
  assert.equal(tree.root.findAll(n=>typeof n.type==='function'&&n.type.name==='AnswerCard').length,0);
 }finally{if(tree)await act(async()=>tree.unmount());console.error=oldError;}
}
assert.deepEqual(actions,['extract']);globalThis.fetch=oldFetch;
console.log('PASS: the single chat flow shows required unknowns, ask first, and skip all unknowns without calculation or estimation.');

// A purchase today is complete: zero is a valid horizon, not a missing deadline.
const today=JSON.parse(fs.readFileSync('tests/fixtures/today-purchase.json','utf8'));
const todayActions=[];let todayTree;
globalThis.fetch=async url=>{
 const action=url.split('/').at(-1);todayActions.push(action);
 assert.ok(['extract','calculate'].includes(action));
 return {ok:true,json:async()=>structuredClone(action==='extract'?today.extraction:today.calculation)};
};
try{
 console.error=()=>{};
 await act(async()=>{todayTree=renderer.create(React.createElement(ChatApp));});
 await act(async()=>todayTree.root.findByType('textarea').props.onChange({target:{value:'I have $750 for a $900 laptop. Can I buy it today?'}}));
 await act(async()=>todayTree.root.findByType('form').props.onSubmit({preventDefault(){}}));
 assert.deepEqual(todayActions,['extract','calculate']);
 const cards=todayTree.root.findAll(n=>typeof n.type==='function'&&n.type.name==='AnswerCard');
 assert.equal(cards.length,1);assert.match(JSON.stringify(todayTree.toJSON()),/No/);
 assert.equal(todayTree.root.findAll(n=>n.props?.['data-verification-warning']).length,0);
 assert.equal(todayTree.root.findAllByType('button').filter(n=>n.props.children==='Not sure, skip this').length,0);
}finally{
 globalThis.fetch=oldFetch;console.error=oldError;
 if(todayTree)await act(async()=>todayTree.unmount());
}
console.log('PASS: $750 toward a $900 purchase today reaches Main’s answer card without income, expenses or a repeated zero-month deadline question.');
