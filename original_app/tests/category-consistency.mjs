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
const {Understood,WorkingSheet,category}=load(path.resolve('components/chat-parts.tsx'));

// One category rule everywhere: role decides, not source. An approximate amount the user supplied
// (role=known, source=inferred) is "You told me"; only derived values are "I worked out".
const factors=[
 {variable:'goal_amount',value:3000,unit:'$',role:'known',source:'inferred',source_detail:'Approximate amount supplied by the user',evidence:{source:'question',quote:'may cost $3000'}},
 {variable:'monthly_income',value:2000,unit:'$/month',role:'known',source:'stated',source_detail:'Supplied',evidence:{source:'question',quote:'$2000'}},
 {variable:'monthly_surplus',value:350,unit:'$/month',role:'derived',source:'inferred',source_detail:'Worked out'},
 {variable:'current_savings',value:900,unit:'$',role:'known',source:'stated',source_detail:'From profile',evidence:{source:'profile',quote:'900',variable:'current_savings'}},
 {variable:'monthly_expenses',value:null,unit:'$/month',role:'missing',source:'missing',source_detail:'Unknown'},
];
assert.deepEqual(factors.map(category),['stated','stated','inferred','profile','missing']);
const extraction={model:'savings_goal',goal_summary:'Trip',confidence_note:'',clarification_questions:[],factors,assumptions:factors.map(({variable,value,unit,source,source_detail})=>({variable,value,unit,source,source_detail}))};
let tree;const old=console.error;console.error=()=>{};
try{await act(async()=>{tree=renderer.create(React.createElement('div',null,React.createElement(Understood,{extraction,onPick(){}}),React.createElement(WorkingSheet,{extraction,math:null})));});}finally{console.error=old;}
const chipCategory={};
for(const group of tree.root.findAll(n=>n.props?.className==='chipGroup')){
 const caption=group.find(n=>n.props?.className==='chipCaption').props['data-source'];
 for(const chip of group.findAllByType('button'))chipCategory[chip.findAllByType('span')[0].props.children]=caption;
}
const sheetCategory={};
for(const li of tree.root.findAll(n=>n.type==='li'&&n.props['data-source']))sheetCategory[li.find(n=>n.props?.className==='sheetLabel').props.children]=li.props['data-source'];
assert.ok(Object.keys(chipCategory).length>=5,'every factor shown as a chip');
for(const [label,cat] of Object.entries(chipCategory))assert.equal(sheetCategory[label],cat,`${label}: chip "${cat}" vs sheet "${sheetCategory[label]}"`);
assert.equal(chipCategory['Goal amount'],'stated');
assert.equal(chipCategory['Monthly surplus'],'inferred');
console.log('PASS: chips and working sheet use one category per value (role-based; user-supplied approximations are "You told me", derived values "I worked out", profile values apart).');
