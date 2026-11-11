import type { ModelContext } from '../lib/model-factors';
import { factorGroups } from '../lib/model-factors';
import { label } from '../lib/workspace-model';

// One read-only renderer handles category rows, any number of diners/items,
// custom weights, and transfers. It renders data only, never model-generated JSX.
export function FactorValue({ value, unit = '', depth = 0 }: { value: unknown; unit?: string | null; depth?: number }) {
  let data = value;
  if (typeof data === 'string' && /^[\[{]/.test(data.trim())) {
    try { data = JSON.parse(data); } catch { /* preserve ordinary text */ }
  }
  if (data === null || data === undefined) return <>Unknown</>;
  if (depth < 5 && Array.isArray(data)) return <ul>{data.map((item, i) => <li key={i}><FactorValue value={item} depth={depth + 1} /></li>)}</ul>;
  if (depth < 5 && typeof data === 'object') return <dl className="scenario-summary">{Object.entries(data as Record<string, unknown>).map(([key, item]) => <div key={key}><dt>{label(key)}</dt><dd><FactorValue value={item} depth={depth + 1} /></dd></div>)}</dl>;
  if (typeof data === 'object') return <>{JSON.stringify(data)}</>;
  const text = typeof data === 'boolean' ? data ? 'Yes' : 'No' : String(data);
  return <>{unit?.startsWith('$') && typeof data === 'number' ? `$${data.toLocaleString('en-US', { maximumFractionDigits: 2 })}` : text}{typeof data === 'number' && unit && unit !== '$' && unit !== 'text' ? unit === '$/month' ? ' / month' : ` ${unit}` : ''}</>;
}

export function ModelResultDetails({ context }: { context: ModelContext }) {
  if (!context.factors?.length) return null;
  return <div aria-label="Financial model factors">{factorGroups(context.factors, context.target_variable).map(group => <section key={group.role}>
    <p className="source-caption">{group.title}</p>
    <dl className="scenario-summary">{group.factors.map(f => <div key={f.variable} title={`${f.source}: ${f.source_detail}`}>
      <dt>{label(f.variable)}</dt>
      <dd><FactorValue value={f.value} unit={f.unit} /></dd>
    </div>)}</dl>
  </section>)}</div>;
}
