import { money, label } from './workspace-model';
const labels: Record<string,string> = { contribution_entries:'Deposit schedule', income_entries:'Income', spending_entries:'Spending', expense_categories:'Expenses', shared_items:'Shared purchases', items:'Purchases', goal_deadline:'When you need it', contribution_months:'Monthly deposits', available_savings:'Available savings' };
export const factLabel=(name:string)=>labels[name]??label(name.replace(/_entries$/, ''));
export function factText(value:unknown,unit?:string|null,variable=''):string {
 let data=value;
 if(typeof data==='string'&&/^[\[{]/.test(data.trim()))try{data=JSON.parse(data);}catch{}
 if(data==null||data==='')return 'Unknown';
 if(variable==='goal_deadline'&&data===0&&unit==='months')return 'Today';
 if(Array.isArray(data))return data.map(item=>{
  if(item&&typeof item==='object'&&'amount' in item){
   const e=item as Record<string,unknown>;
   const frequency=String(e.frequency??'');
   const periods:Record<string,string>={weekly:'week',monthly:'month',daily:'day',biweekly:'two weeks',yearly:'year'};
   const amount=Number.isFinite(Number(e.amount))?money(Number(e.amount)):String(e.amount);
   const parts=[e.name?`${e.name}: ${amount}`:amount];
   if(frequency)parts.push(`every ${periods[frequency]??frequency}`);
   if(e.count!=null)parts.push(`${e.count} deposits`);
   if(e.timing)parts.push(String(e.timing).replaceAll('_',' '));
   if(Array.isArray(e.shared_by))parts.push(`shared by ${e.shared_by.join(', ')}`);
   return parts.join(' · ');
  }
  return factText(item,unit);
 }).join('; ');
 if(typeof data==='object')return Object.entries(data as Record<string,unknown>).map(([k,v])=>`${label(k)}: ${factText(v,typeof v==='number'?'$':null)}`).join('; ');
 if(typeof data==='number')return unit?.startsWith('$')?money(data)+(unit==='$/month'?' / month':''):String(data)+(unit&&unit!=='text'?` ${unit}`:'');
 return String(data);
}
