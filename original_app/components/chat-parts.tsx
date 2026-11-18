'use client';
// Presentational pieces for the chat view. No service calls and no state beyond local UI state.
import { VerificationWarning } from './verification-warning';
import { useState } from 'react';
import { AnswerVisuals } from './answer-visuals';
import { PresentationBoundary } from './presentation-boundary';
import { extractionFactors, factorGroups, displayFactors } from '../lib/model-factors';
import { factLabel, factText } from '../lib/fact-presentation';
import { type CalculationResponse } from '../lib/calculation-contract';
import type { Assumption, ExtractionResponse } from '../lib/extraction';
import { money } from '../lib/workspace-model';
import s from '../app/chat/chat.module.css';

export function show(a: Pick<Assumption, 'value' | 'unit'>): string {
  if (a.value === null || a.value === '') return 'unknown';
  const unit = a.unit ?? '';
  if (typeof a.value === 'number') {
    if (unit.startsWith('$')) return `${money(a.value)}${unit === '$/month' ? '/mo' : unit === '$/occurrence' ? ' each time' : ''}`;
    return `${a.value.toLocaleString('en-US')}${unit && unit !== 'text' ? ` ${unit}` : ''}`;
  }
  return a.value;
}

// Read-only summary of what the model understood. Clicking a chip pre-fills the composer, so
// corrections happen in conversation rather than in form fields.
export function Understood({ extraction, onPick }: { extraction: ExtractionResponse; onPick: (text: string) => void }) {
  const groups = factorGroups(extractionFactors(extraction).filter(a => a.variable !== 'goal_description' && (extraction.factors || !(a.variable === 'monthly_surplus' && a.source === 'missing'))), extraction.target_variable);
  return <div>
    <p className={s.bubbleText}>{typeof extraction.assistant_message === 'string' && extraction.assistant_message.trim() ? extraction.assistant_message : extraction.goal_summary || 'Here is what I understood.'}</p>
    {groups.map(g => <div key={g.source} className={s.chipGroup}>
      <span className={s.chipCaption}>{g.title}</span>
      <div className={s.chips}>{g.factors.map(a => <button key={a.variable} type="button" className={`${s.chip} ${s[g.source]}`} title={`${a.source}: ${a.source_detail}`}
        onClick={() => onPick(`Actually, ${factLabel(a.variable).toLowerCase()} is `)}>
        <span>{factLabel(a.variable)}</span>{a.role !== 'missing' && <strong>{factText(a.value, a.unit, a.variable)}</strong>}</button>)}</div>
    </div>)}
    <p className={s.hint}>Tap anything to correct it, or just tell me in your own words.</p>
  </div>;
}

export function Typing() {
  return <span className={s.typing} aria-label="Thinking"><i /><i /><i /></span>;
}

export function QuickReplies({ replies, onPick, disabled }: { replies: string[]; onPick: (text: string) => void; disabled: boolean }) {
  return <div className={s.replies}>{replies.map(r => <button key={r} type="button" disabled={disabled} onClick={() => onPick(r)}>{r}</button>)}</div>;
}

export function QuestionText({ text, verification }: { text: string; verification?: CalculationResponse['verification'] }) {
  return <p className={s.bubbleText}>{text}<VerificationWarning verification={verification} /></p>;
}

// Keep the answer box independent of inputs, worksheet data and presentation details.
export function AnswerCard({ response }: { response: CalculationResponse; interactive: boolean; params: Record<string, string>; onParam: (key: string, value: string) => void }) {
  const ok = response.status === 'ready' || response.status === 'conditional';
  if (!ok) return <QuestionText text={response.message ?? ''} verification={response.verification} />;
  return <div className={`${s.answer} ${s.answerBox}`}>
    <p className={s.headline}>{response.answer.headline}<VerificationWarning verification={response.verification} /></p>
  </div>;
}

// Grace's narrative, charts, math disclosure and what-if interactions live below
// the answer. Each optional section can fail without taking the answer with it.
export function AnswerSupporting({ response, interactive, disabled, onAsk }: { response: CalculationResponse; interactive: boolean; disabled: boolean; onAsk: (text: string) => void }) {
  if (response.status !== 'ready' && response.status !== 'conditional') return null;
  return <div className={s.supporting} aria-label="Supporting explanation">
    {response.narrative && <p className={s.explain}>{response.narrative.text}</p>}
    {response.visuals && <PresentationBoundary resetKey={response.visuals} fallback={null}><AnswerVisuals v={response.visuals} /></PresentationBoundary>}
    <MathPanel response={response} />
    {interactive && !!response.narrative?.suggestions.length && <div><span className={s.chipCaption}>Try a what-if</span><QuickReplies replies={response.narrative.suggestions} disabled={disabled} onPick={onAsk} /></div>}
  </div>;
}

function MathPanel({ response }: { response: CalculationResponse }) {
  const [open, setOpen] = useState(false);
  if (!response.explanations.length && !response.assumptions.length && !response.limitations.length) return null;
  return <div className={s.math}><button type="button" className={s.link} aria-expanded={open} onClick={() => setOpen(value => !value)}>{open ? 'Hide the math' : 'Show the math'}</button>
    {open && <div>{response.explanations.map((step, i) => <p key={i}><strong>{step.label}</strong><br />{step.text}</p>)}
      {response.assumptions.map(item => <p key={item.id} className={s.muted}>Assumption: {item.text}</p>)}
      {response.limitations.map((item, i) => <p key={i} className={s.muted}>{item}</p>)}</div>}
  </div>;
}

// Always-visible record of every value and where it came from: the "framework in the background".
export function WorkingSheet({ extraction, math }: { extraction: ExtractionResponse | null; math: CalculationResponse | null }) {
  const factors = new Map(extraction ? extractionFactors(extraction).map(f => [f.variable, f]) : []);
  for (const factor of math?.factors ?? []) factors.set(factor.variable, factor);
  return <aside className={s.sheet} aria-label="Working sheet">
    <h2>Working sheet</h2>
    {!extraction ? <p className={s.muted}>Everything I understand will be listed here, with where it came from.</p> : <ul>
      {displayFactors([...factors.values()], math?.target_variable ?? extraction.target_variable).map(a => <li key={a.variable} title={`${a.source}: ${a.source_detail}`}>
        <span className={`${s.dot} ${s[a.source]}`} aria-label={a.source} /><span className={s.sheetLabel}>{factLabel(a.variable)}</span><strong className={s.sheetValue}>{factText(a.value, a.unit, a.variable)}</strong></li>)}</ul>}
    <p className={s.legend}><span className={`${s.dot} ${s.stated}`} /> stated <span className={`${s.dot} ${s.inferred}`} /> inferred <span className={`${s.dot} ${s.missing}`} /> missing</p>
    {math && (math.status === 'ready' || math.status === 'conditional') && math.explanations.length > 0 && <><h2>The math</h2>{math.explanations.map((e, i) => <p key={i} className={s.sheetMath}><strong>{e.label}</strong><br />{e.text}</p>)}</>}
  </aside>;
}

// The four-step progression guides the conversation but is not shown as steps: just a quiet status line.
const STATUS = ['Getting the picture', 'A couple of questions', 'Running the numbers', 'Here’s where you stand'];
export function Status({ stage, active }: { stage: number; active: boolean }) {
  return active ? <p className={s.status} role="status">{STATUS[stage]}</p> : null;
}
