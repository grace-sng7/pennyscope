'use client';
// Presentational pieces for the chat view. No service calls and no state beyond local UI state.
import { VerificationWarning } from './verification-warning';
import { extractionFactors, factorGroups, displayFactors } from '../lib/model-factors';
import { FactorValue } from './model-result-details';
import { type CalculationResponse } from '../lib/calculation-contract';
import type { Assumption, ExtractionResponse } from '../lib/extraction';
import { label, money } from '../lib/workspace-model';
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

function preview(value: Pick<Assumption, 'value' | 'unit'>) {
  if (typeof value.value === 'string' && /^[\[{]/.test(value.value.trim())) {
    try {
      const data = JSON.parse(value.value);
      if (Array.isArray(data)) return data.every(v => typeof v === 'string' || typeof v === 'number') ? data.join(', ') : `${data.length} entries`;
      if (data && typeof data === 'object') return `${Object.keys(data).length} entries`;
    } catch { /* show ordinary text */ }
  }
  return show(value);
}

// Read-only summary of what the model understood. Clicking a chip pre-fills the composer, so
// corrections happen in conversation rather than in form fields.
export function Understood({ extraction, onPick }: { extraction: ExtractionResponse; onPick: (text: string) => void }) {
  const groups = factorGroups(extractionFactors(extraction).filter(a => a.variable !== 'goal_description' && (extraction.factors || !(a.variable === 'monthly_surplus' && a.source === 'missing'))), extraction.target_variable);
  return <div>
    <p className={s.bubbleText}>{extraction.goal_summary || 'Here is what I understood.'}</p>
    {groups.map(g => <div key={g.source} className={s.chipGroup}>
      <span className={s.chipCaption}>{g.title}</span>
      <div className={s.chips}>{g.factors.map(a => <button key={a.variable} type="button" className={`${s.chip} ${s[g.source]}`} title={`${a.source}: ${a.source_detail}`}
        onClick={() => onPick(`Actually, ${label(a.variable).toLowerCase()} is `)}>
        <span>{label(a.variable)}</span>{a.role !== 'missing' && <strong>{preview(a)}</strong>}</button>)}</div>
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
  return <div className={s.answer}>
    <p className={s.headline}>{response.answer.headline}<VerificationWarning verification={response.verification} /></p>
  </div>;
}

// Always-visible record of every value and where it came from: the "framework in the background".
export function WorkingSheet({ extraction, math }: { extraction: ExtractionResponse | null; math: CalculationResponse | null }) {
  return <aside className={s.sheet} aria-label="Working sheet">
    <h2>Working sheet</h2>
    {!extraction ? <p className={s.muted}>Everything I understand will be listed here, with where it came from.</p> : <ul>
      {displayFactors(math?.factors ?? extractionFactors(extraction), math?.target_variable ?? extraction.target_variable).map(a => <li key={a.variable} title={`${a.source}: ${a.source_detail}`}>
        <span className={`${s.dot} ${s[a.source]}`} aria-label={a.source} /><span className={s.sheetLabel}>{label(a.variable)}</span><strong><FactorValue value={a.value} unit={a.unit} /></strong></li>)}</ul>}
    <p className={s.legend}><span className={`${s.dot} ${s.stated}`} /> stated <span className={`${s.dot} ${s.inferred}`} /> inferred <span className={`${s.dot} ${s.missing}`} /> missing</p>
    {math && (math.status === 'ready' || math.status === 'conditional') && math.explanations.length > 0 && <><h2>The math</h2>{math.explanations.map((e, i) => <p key={i} className={s.sheetMath}><strong>{e.label}</strong><br />{e.text}</p>)}</>}
  </aside>;
}

// The four-step progression guides the conversation but is not shown as steps: just a quiet status line.
const STATUS = ['Getting the picture', 'A couple of questions', 'Running the numbers', 'Here’s where you stand'];
export function Status({ stage, active }: { stage: number; active: boolean }) {
  return active ? <p className={s.status} role="status">{STATUS[stage]}</p> : null;
}
