'use client';
// Adapted from Grace 086b79b. Charts draw optional backend presentation values.
// Exact legends and expandable lists keep every figure readable without tables.
import { useState, type ReactNode } from 'react';
import type { BudgetSplit, PlanOption, Visuals } from '../lib/answer-presentation';
import { money } from '../lib/workspace-model';
import s from '../app/chat/chat.module.css';


// Series colours by role (validated: blue/aqua/orange pass the CVD and normal-vision checks on light surfaces).
const C = { income: '#2a78d6', savings: '#1baf7a', left: '#eb6834', short: 'transparent' } as const;
const GREYS = ['#B9B4AA', '#CFCAC0', '#A39E94', '#DDD8CE', '#928D84'];

type Segment = { key: string; label: string; value: number; color: string; hatch?: boolean; note?: string };

// One horizontal 100% bar with a 2px surface gap between segments and a hover tooltip.
function StackedBar({ segments, total, ariaLabel }: { segments: Segment[]; total: number; ariaLabel: string }) {
  const [tip, setTip] = useState<{ x: number; seg: Segment } | null>(null);
  const shown = segments.filter(x => x.value > 0.005);
  return <div className={s.barWrap} onMouseLeave={() => setTip(null)}>
    <div className={s.bar} role="img" aria-label={ariaLabel}>
      {shown.map(seg => <span key={seg.key} className={`${s.barSeg} ${seg.hatch ? s.hatch : ''}`}
        style={{ flexGrow: seg.value, background: seg.hatch ? undefined : seg.color }}
        onMouseMove={e => { const box = e.currentTarget.parentElement!.getBoundingClientRect(); setTip({ x: e.clientX - box.left, seg }); }} />)}
    </div>
    {tip && <div className={s.tip} style={{ left: tip.x }}><strong>{tip.seg.label}</strong> {money(tip.seg.value)}{total > 0 ? ` · ${Math.round(tip.seg.value / total * 100)}%` : ''}{tip.seg.note ? <><br /><span>{tip.seg.note}</span></> : null}</div>}
  </div>;
}

function Legend({ segments }: { segments: Segment[] }) {
  return <ul className={s.legendList}>{segments.filter(x => x.value > 0.005).map(seg => <li key={seg.key}>
    <span className={`${s.swatch} ${seg.hatch ? s.hatch : ''}`} style={{ background: seg.hatch ? undefined : seg.color }} aria-hidden="true" />
    <span>{seg.label}</span><strong>{money(seg.value)}</strong></li>)}</ul>;
}

function Figure({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return <figure className={s.figure}><figcaption><strong>{title}</strong>{sub && <span>{sub}</span>}</figcaption>{children}</figure>;
}

function budgetSegments(b: BudgetSplit, goalLabel: string): Segment[] {
  return [
    ...b.expenses.map((e, i) => ({ key: `e${i}`, label: e.label, value: e.amount, color: GREYS[i % GREYS.length] })),
    { key: 'goal', label: goalLabel, value: b.goal, color: C.income },
    ...(b.left_over >= 0 ? [{ key: 'left', label: 'Left over', value: b.left_over, color: C.left }] : []),
  ];
}

function BudgetFigure({ b, title, goalLabel }: { b: BudgetSplit; title: string; goalLabel: string }) {
  const segs = budgetSegments(b, goalLabel);
  const over = b.left_over < 0;
  return <Figure title={title} sub={b.basis === 'surplus' ? `out of ${money(b.income)} available after current expenses` : `out of ${money(b.income)} coming in`}>
    <StackedBar segments={segs} total={Math.max(b.income, segs.reduce((a, x) => a + x.value, 0))} ariaLabel={`${title}: ${segs.map(x => `${x.label} ${money(x.value)}`).join(', ')}`} />
    <Legend segments={segs} />
    {over && <p className={s.warnLine}>⚠ That’s {money(-b.left_over)} more than comes in each month.</p>}
  </Figure>;
}

// Anchor labels to the question's reference date rather than the browser clock.
const monthName = (offset: number, base?: string) => {
  if (!base) return `Month ${offset}`;
  const [year, month] = base.split('-').map(Number);
  return new Date(year, month - 1 + offset, 1).toLocaleString('en-US', { month: 'short', year: '2-digit' });
};

function Timeline({ timeline, goal, fromSavings, base }: { timeline: { month: number; set_aside: number }[]; goal?: number; fromSavings: number; base?: string }) {
  const [hover, setHover] = useState<number | null>(null);
  const [details, setDetails] = useState(false);
  if (!timeline.length) return null;
  const top = Math.max(1, goal ?? 0, ...timeline.map(t => t.set_aside + (t.month === timeline.length ? fromSavings : 0)));
  const h = (v: number) => `${Math.max(0, v / top * 100)}%`;
  const last = timeline.length;
  return <Figure title="Month by month" sub={goal ? 'total set aside toward the goal' : 'projected savings balance'}>
    <div className={s.plot} role="img" aria-label={`Savings by month: ${timeline.map(t => `${monthName(t.month, base)} ${money(t.set_aside)}`).join(', ')}.${goal ? ` Goal ${money(goal)}.` : ''}`} onMouseLeave={() => setHover(null)}>
      {goal !== undefined && <div className={s.goalLine} style={{ bottom: h(goal) }}><span>Goal {money(goal)}</span></div>}
      {timeline.map(t => <div key={t.month} className={s.col} onMouseEnter={() => setHover(t.month)}>
        {t.month === last && fromSavings > 0.005 && <span className={s.colBar} style={{ height: h(fromSavings), background: C.savings }} />}
        <span className={s.colBar} style={{ height: h(t.set_aside), background: C.income, opacity: hover === null || hover === t.month ? 1 : .55 }} />
        {hover === t.month && <div className={s.tip} style={{ left: '50%', bottom: 'auto', top: 0 }}><strong>{monthName(t.month, base)}</strong> {money(t.set_aside)}{t.month === last && fromSavings > 0.005 ? ` + ${money(fromSavings)} from savings` : ''}</div>}
      </div>)}
    </div>
    <div className={s.colLabels} aria-hidden="true">{timeline.map(t => <span key={t.month}>{monthName(t.month, base)}</span>)}</div>
    <Legend segments={[{key:'income',label:goal ? 'Set aside from income' : 'Projected savings',value:timeline[last - 1].set_aside,color:C.income},...(fromSavings > 0.005 ? [{key:'savings',label:'From savings at the end',value:fromSavings,color:C.savings}] : [])]} />
    <button type="button" className={s.link} aria-expanded={details} onClick={() => setDetails(o => !o)}>{details ? 'Hide monthly details' : 'Show monthly details'}</button>
    {details && <ul className={s.detailList}>{timeline.map(t => <li key={t.month}><strong>{monthName(t.month, base)}</strong><span>{money(t.set_aside)} set aside{goal ? ` · ${Math.min(100, Math.round(t.set_aside / goal * 100))}% of the goal` : ''}</span></li>)}</ul>}
  </Figure>;
}

function OptionsList({ options, kind }: { options: PlanOption[]; kind: Visuals['kind'] }) {
  if (options.length < 2) return null;
  return <Figure title="Your options" sub="same numbers, different ways to get there">
    <ul className={s.planList}>{options.map((o, i) => <li key={i} className={o.current ? s.currentRow : ''}>
      <strong>{o.label}</strong>{o.current && o.label !== 'Current plan' && <span className={s.muted}>Current plan</span>}
      {kind === 'one_time' ? <><span>{o.months === 0 ? 'No monthly deposits' : `${money(o.monthly!)} each month × ${o.months} months`}</span><span>{money(o.from_savings!)} from savings · {money(o.savings_left!)} savings remaining</span></> : <span>{money(o.left_each_month!)} left each month</span>}
      <span>{o.feasible ? o.budget_checked === false ? 'Reaches the goal; monthly budget capacity was not supplied' : '✓ Works with these numbers' : `Does not fit${o.short ? ` · ${money(o.short)} short` : ''}`}</span>
    </li>)}</ul>
  </Figure>;
}

export function AnswerVisuals({ v }: { v: Visuals }) {
  if(v.kind==='deposits')return <Figure title="Savings timeline" sub={`${money(v.start)} starting balance · ${money(v.amount)} each ${v.period}`}>
    <ul className={s.detailList}>{v.timeline.map(t=><li key={t.deposit}><strong>{v.period[0].toUpperCase()+v.period.slice(1)} {t.deposit}</strong><span>{money(t.balance)} after deposit {t.deposit}</span></li>)}</ul>
  </Figure>;
  if (v.kind === 'one_time') {
    const f = v.funding;
    const segs: Segment[] = f ? [
      { key: 'income', label: 'Saved from income', value: f.from_income, color: C.income },
      { key: 'savings', label: 'From your savings', value: f.from_savings, color: C.savings },
      { key: 'short', label: 'Still short', value: f.short, color: C.short, hatch: true },
    ] : [];
    // Only worth a chart when the money comes from more than one place (or falls short).
    const mixed = segs.filter(x => x.value > 0.005).length > 1;
    return <div className={s.visuals}>
      {mixed && f && <Figure title="Where the money comes from" sub={`for the ${money(f.goal)} goal`}>
        <StackedBar segments={segs} total={f.goal} ariaLabel={`Goal ${money(f.goal)}: ${segs.filter(x => x.value > 0).map(x => `${x.label} ${money(x.value)}`).join(', ')}`} />
        <Legend segments={segs} />
      </Figure>}
      {v.budget && <BudgetFigure b={v.budget} title="Your month with this plan" goalLabel="Toward the goal" />}
      {v.timeline && <Timeline timeline={v.timeline} goal={f?.goal} fromSavings={f?.from_savings ?? 0} base={v.base_date} />}
      <OptionsList options={v.options} kind={v.kind} />
    </div>;
  }
  return <div className={s.visuals}>
    {v.budget_now && <BudgetFigure b={v.budget_now} title="Your month now" goalLabel="New cost" />}
    {v.budget_after && <BudgetFigure b={v.budget_after} title="Your month with the new cost" goalLabel="Extra cost" />}
    <OptionsList options={v.options} kind={v.kind} />
  </div>;
}
