// Optional display data only. No model selection, missing-input rules or financial solver.
export interface BudgetSplit { income: number; expenses: { label: string; amount: number }[]; goal: number; left_over: number; basis?: 'income' | 'surplus' }
export interface PlanOption { label: string; current: boolean; feasible: boolean; goal: number; months?: number; monthly?: number; from_savings?: number; savings_left?: number; short?: number; left_each_month?: number; budget_checked?: boolean }
export type Visuals =
 | { kind: 'deposits'; period: 'week'|'month'|'day'; start: number; amount: number; timeline: { deposit: number; balance: number }[] }
 | { kind: 'one_time'; funding?: { goal: number; from_income: number; from_savings: number; short: number }; budget?: BudgetSplit; timeline?: { month: number; set_aside: number }[]; options: PlanOption[]; base_date?: string }
 | { kind: 'recurring'; budget_now?: BudgetSplit; budget_after?: BudgetSplit; options: PlanOption[] };
export interface Narrative { text: string; suggestions: string[] }
const obj=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==='object'&&!Array.isArray(v);
const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);
const amount=(v:unknown):v is number=>finite(v)&&v>=0;
function readBudget(v:unknown):BudgetSplit|undefined {
 if(!obj(v)||!amount(v.income)||!amount(v.goal)||!finite(v.left_over)||!Array.isArray(v.expenses))return;
 if(v.expenses.some(e=>!obj(e)||typeof e.label!=='string'||!amount(e.amount)))return;
 const expenses=v.expenses as BudgetSplit['expenses'];
 if(Math.abs(expenses.reduce((sum,e)=>sum+e.amount,0)+v.goal+v.left_over-v.income)>.03)return;
 return {income:v.income,expenses,goal:v.goal,left_over:v.left_over,...(v.basis==='surplus'?{basis:'surplus' as const}:{})};
}
export function readNarrative(v:unknown):Narrative|undefined {
 if(!obj(v)||typeof v.text!=='string'||!v.text.trim())return;
 return {text:v.text.trim(),suggestions:Array.isArray(v.suggestions)?v.suggestions.filter((s):s is string=>typeof s==='string'&&!!s.trim()&&s.length<=100).slice(0,3):[]};
}
export function readVisuals(v:unknown):Visuals|undefined {
 if(!obj(v))return;
 if(v.kind==='deposits'){
  if(!['week','month','day'].includes(String(v.period))||!amount(v.start)||!amount(v.amount)||!Array.isArray(v.timeline)||!v.timeline.length||v.timeline.length>60)return;
  if(!v.timeline.every((t,i)=>obj(t)&&t.deposit===i+1&&amount(t.balance)&&Math.abs(t.balance-(v.start as number)-(v.amount as number)*(i+1))<.02))return;
  return v as unknown as Extract<Visuals,{kind:'deposits'}>;
 }
 if(v.kind!=='one_time'&&v.kind!=='recurring')return;
 const options:PlanOption[]=Array.isArray(v.options)?v.options.flatMap((o):PlanOption[]=>{
  if(!obj(o)||typeof o.label!=='string'||typeof o.current!=='boolean'||typeof o.feasible!=='boolean'||!amount(o.goal))return [];
  if(v.kind==='one_time'&&(!amount(o.months)||!Number.isInteger(o.months)||!amount(o.monthly)||!amount(o.from_savings)||!amount(o.savings_left)))return [];
  if(v.kind==='recurring'&&!finite(o.left_each_month))return [];
  if(o.short!==undefined&&!amount(o.short))return [];
  return [o as unknown as PlanOption];
 }):[];
 if(v.kind==='recurring'){
  const budget_now=readBudget(v.budget_now),budget_after=readBudget(v.budget_after);
  if(!budget_now&&!budget_after&&options.length<2)return;
  return {kind:v.kind,budget_now,budget_after,options};
 }
 const f=v.funding;
 const funding=obj(f)&&amount(f.goal)&&f.goal>0&&amount(f.from_income)&&amount(f.from_savings)&&amount(f.short)&&Math.abs(f.goal-f.from_income-f.from_savings-f.short)<.03?f as unknown as NonNullable<Extract<Visuals,{kind:'one_time'}>['funding']>:undefined;
 const budget=readBudget(v.budget);
 const timeline=Array.isArray(v.timeline)&&v.timeline.length>0&&v.timeline.length<=60&&v.timeline.every((t,i)=>obj(t)&&t.month===i+1&&amount(t.set_aside))?v.timeline as {month:number;set_aside:number}[]:undefined;
 if(!funding&&!budget&&!timeline&&options.length<2)return;
 return {kind:v.kind,funding,budget,timeline,options,...(typeof v.base_date==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v.base_date)?{base_date:v.base_date}:{})};
}
