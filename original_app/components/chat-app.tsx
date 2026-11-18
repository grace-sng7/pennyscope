'use client';
// Conversational front end. The framework is still: extract -> clarify -> calculate -> answer,
// but each stage is a chat turn instead of a card. Services are the same ones the dashboard uses.
import { useCallback, useEffect, useRef, useState } from 'react';
import type { CalculationRequest, CalculationResponse, CalculationService } from '../lib/calculation-contract';
import { parsePlainChat, type PlainChat } from '../lib/plain-chat';
import { PresentationBoundary, PlainResult } from './presentation-boundary';
import { extractionFactors } from '../lib/model-factors';
import type { ExtractionResponse, ExtractionService } from '../lib/extraction';
import { liveCalculationService, liveExtractionService, recoverPlainChat } from '../lib/http-services';
import { calculationService as mockCalculation, extractionService as mockExtraction } from '../lib/services';
import { applyLocalAnswer, parseSimpleAnswer } from '../lib/local-answer';
import { label, money } from '../lib/workspace-model';
import { AnswerCard, AnswerSupporting, QuestionText, QuickReplies, Status, Typing, Understood, WorkingSheet, show } from './chat-parts';
import { Coin } from './coin';
import { ProfilePanel } from './profile-panel';
import { clearProfile, financialProfile, hasProfile, loadProfile, monthlyExpenses, saveProfile, type Profile } from '../lib/profile';
import s from '../app/chat/chat.module.css';

const live = process.env.NEXT_PUBLIC_BACKEND_MODE === 'live';
const extraction: ExtractionService = live ? liveExtractionService : mockExtraction;
const calculator: CalculationService = live ? liveCalculationService : mockCalculation;

const SKIP = 'Not sure, skip this';
const RETRY = 'Try again';
const ESTIMATE = 'Use a rough estimate';
const DONT_KNOW = /(don'?t know|dont know|not sure|no idea|idk|unsure|can'?t say)/i;
// A bare "I don't know": no numbers and short. Mixed answers ("income 5000, cost not sure") go to the model instead.
const isDontKnow = (text: string) => DONT_KNOW.test(text) && !/\d/.test(text) && text.length <= 60;
const SUGGESTIONS = [
  'I make $2,400 a month after tax, rent is $1,000 and I spend about $600 on everything else. I have $900 saved. Can I afford a $2,500 laptop by next March?',
  'My friends want to do a spring break trip to Miami but I don’t know if I can afford it',
  'I want to move to a $1,400/month apartment in February, I currently pay $1,000 rent. Can I swing it?',
];

type Msg =
  | { id: number; role: 'user'; text: string }
  | { id: number; role: 'bot'; kind: 'text'; text: string; verification?: CalculationResponse['verification']; note?: string; replies?: string[] }
  | { id: number; role: 'bot'; kind: 'understood'; extraction: ExtractionResponse }
  | { id: number; role: 'bot'; kind: 'answer'; response: CalculationResponse }
  | { id: number; role: 'bot'; kind: 'typing' };
type NewMsg = Msg extends infer M ? M extends { id: number } ? Omit<M, 'id'> : never : never;

const context = () => {
  const date = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  return { reference_date: date, timezone: 'America/New_York' };
};
const request = (original: string, ex: ExtractionResponse, parameters: Record<string, string>): CalculationRequest =>
  ({ originalQuestion: original, extraction: ex, edits: {}, answers: {}, parameters, answerFactBindings: {} });

// Which assumptions did a correction actually change? Used for the "Got it" acknowledgement.
function changes(before: ExtractionResponse, after: ExtractionResponse): string[] {
  const old = new Map(before.assumptions.map(a => [a.variable, a]));
  return after.assumptions.filter(a => a.source !== 'missing' && a.variable !== 'goal_description' && (() => { const p = old.get(a.variable); return !p || p.value !== a.value || p.source === 'missing'; })())
    .slice(0, 4).map(a => `${label(a.variable)}: ${show(a)}`);
}

export default function ChatApp() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState(0);
  const [ex, setEx] = useState<ExtractionResponse | null>(null);
  const [reviewedMath, setReviewedMath] = useState<{ snapshot: ExtractionResponse; response: CalculationResponse } | null>(null);
  const [params, setParams] = useState<Record<string, string>>({});
  const [sheetOpen, setSheetOpen] = useState(false);
  const [profile, setProfile] = useState<Profile>({});
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef<Profile>({});
  const idRef = useRef(0);
  const exRef = useRef<ExtractionResponse | null>(null);
  const originalRef = useRef('');
  const recoveryUsed = useRef(false);
  const latestMessage = useRef('');
  const plainQuestion = useRef<string | null>(null);
  const paramsRef = useRef<Record<string, string>>({});
  const asked = useRef<Record<string, number>>({});
  const skipped = useRef<Set<string>>(new Set());
  const current = useRef<{ targets: string[]; question: string; required: boolean } | null>(null);
  const pendingUnknowns = useRef<string[] | null>(null);   // required items still unknown
  const retry = useRef<(() => Promise<void>) | null>(null);
  const calcSeq = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  useEffect(() => { if (msgs.length) bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [msgs]);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  // Read the saved profile after mount (browser storage isn't available during server rendering).
  useEffect(() => { const p = loadProfile(); profileRef.current = p; setProfile(p); }, []);
  // Profile figures travel with every extract/correct request; the backend uses them as evidence.
  const withProfile = () => { const fp = financialProfile(profileRef.current); return fp ? { financial_profile: fp } : {}; };

  const push = (m: NewMsg) => setMsgs(list => [...list.filter(x => !('kind' in x && x.kind === 'typing')), { ...m, id: ++idRef.current } as Msg]);
  const bot = (textValue: string, extra: { note?: string; replies?: string[]; verification?: CalculationResponse['verification'] } = {}) => push({ role: 'bot', kind: 'text', text: textValue, ...extra });
  const typing = () => push({ role: 'bot', kind: 'typing' });
  const setExtraction = (value: ExtractionResponse) => { exRef.current = value; setEx(value); };

  const showPlain = (reply: PlainChat) => {
    current.current = null;
    plainQuestion.current = reply.kind === 'question' ? reply.text : null;
    setStage(reply.kind === 'question' ? 1 : 3);
    bot(reply.text, { verification: reply.verification });
  };
  const consumePlainExtraction = (result: ExtractionResponse) => {
    const reply = parsePlainChat(result.chat_fallback);
    if (!reply) return false;
    const before = exRef.current;
    const facts = new Map((before?.assumptions ?? []).map(a => [a.variable, a]));
    for (const a of result.assumptions) if (a.value !== null) facts.set(a.variable, a);
    if (!before || result.assumptions.some(a => a.value !== null && before.assumptions.find(old => old.variable === a.variable)?.value !== a.value)) {
      const sheet = { ...result, assumptions: [...facts.values()] };
      delete sheet.chat_fallback;
      setExtraction(sheet);
    }
    showPlain(reply);
    return true;
  };

  // Next clarification worth asking: skip anything already stated, skipped by the user, or asked twice.
  const nextQuestion = (value: ExtractionResponse) => {
    for (const q of value.clarification_questions) {
      if (q.required !== true) continue;
      if (q.target_variable === value.target_variable) continue;
      if (value.factors) {
        const factor = extractionFactors(value).find(f => f.variable === q.target_variable);
        if (!factor || factor.relevant === false || factor.role !== 'missing' || q.target_variable === value.target_variable) continue;
      }
      const a = value.assumptions.find(x => x.variable === q.target_variable);
      if (skipped.current.has(q.target_variable) || a?.source === 'stated' || (asked.current[q.target_variable] ?? 0) >= 2) continue;
      return { target: q.target_variable, question: q.question, why: q.why_it_matters, required: q.required === true };
    }
    return null;
  };
  const ask = (targets: string[], question: string, why?: string, required = false, verification?: CalculationResponse['verification']) => {
    for (const t of targets) asked.current[t] = (asked.current[t] ?? 0) + 1;
    current.current = { targets, question, required }; pendingUnknowns.current = null;
    setStage(1);
    bot(question, { note: why, replies: [SKIP], verification });
  };

  async function calculate(value: ExtractionResponse) {
    setStage(2); typing();
    const run = async () => {
      const response = await calculator.calculate(request(originalRef.current, value, paramsRef.current));
      if (response.factors?.length) setReviewedMath({ snapshot: value, response });
      if (response.chat_fallback) { showPlain(response.chat_fallback); return; }
      if (response.status === 'ready' || response.status === 'conditional') {
        setReviewedMath({ snapshot: value, response });
        current.current = null; setStage(3); push({ role: 'bot', kind: 'answer', response });
        return;
      }
      if (response.status === 'needs_input') {
        const askable = response.questions.filter(q => q.required).map(q => ({ q, target: q.binding.kind === 'fact' ? value.assumptions[q.binding.index]?.variable ?? q.id : q.binding.key }))
          .filter(x => !skipped.current.has(x.target) && (asked.current[x.target] ?? 0) < 2);
        if (askable.length) { ask([askable[0].target], askable[0].q.label, askable[0].q.help, true, response.verification); return; }
        // Unknown personal facts are not typical-value estimates. Keep them
        // visible and pause the verdict if the user cannot supply them yet.
        const stuck = response.questions.filter(q => q.required).map(q => q.binding.kind === 'fact' ? value.assumptions[q.binding.index]?.variable ?? q.id : q.binding.key);
        if (stuck.length) {
          current.current = null; pendingUnknowns.current = stuck; setStage(1);
          const unknowns = value.clarification_questions.filter(q => q.required === true).map(q => label(q.target_variable).toLowerCase());
          bot(`I can’t determine this yet. Still unknown: ${(unknowns.length ? unknowns : stuck.map(t => label(t).toLowerCase())).join(', ')}. Tell me any of these when you know them; I’ll keep the question open.`);
          return;
        }
        current.current = null; setStage(1);
        bot(`I can’t run the numbers yet. ${response.message} Tell me any of the missing pieces whenever you’re ready, and I’ll pick it back up.`);
        return;
      }
      current.current = null;
      bot(response.message ?? 'I can’t calculate this kind of question yet, but everything you told me is saved on the working sheet.');
    };
    retry.current = async () => { setBusy(true); try { await run(); } catch { await failed(); } finally { setBusy(false); } };
    try { await run(); } catch { await failed(); }
  }
  const failed = async () => {
    if (recoveryUsed.current) {
      bot('I kept your confirmed information, but could not complete the requested result in this attempt.');
      return;
    }
    recoveryUsed.current = true;
    const reply = await recoverPlainChat(originalRef.current || latestMessage.current, exRef.current?.assumptions ?? [], latestMessage.current !== originalRef.current ? latestMessage.current : undefined);
    showPlain(reply);
  };

  async function proceed(value: ExtractionResponse) {
    const q = nextQuestion(value);
    if (q) { ask([q.target], q.question, q.why, q.required); return; }
    const unknowns = value.clarification_questions.filter(q => q.required === true);
    if (unknowns.length) {
      current.current = null; pendingUnknowns.current = unknowns.map(q => q.target_variable); setStage(1);
      bot(`I can’t determine this yet. Still unknown: ${unknowns.map(q => label(q.target_variable).toLowerCase()).join(', ')}. Share any of these when you know them; I’ll keep the question open.`);
      return;
    }
    await calculate(value);
  }

  async function send(raw: string) {
    const message = raw.trim();
    if (!message || busy) return;
    recoveryUsed.current = false; latestMessage.current = message;
    setText(''); push({ role: 'user', text: message });
    if (message === RETRY && retry.current) { setBusy(true); typing(); try { await retry.current(); } finally { setBusy(false); } return; }
    setBusy(true); typing();
    try {
      const before = exRef.current;
      const pending = pendingUnknowns.current ?? (current.current?.required ? current.current.targets : null);
      if (before && pending && message === ESTIMATE) {
        // A hypothetical balance must be chosen by the user, not guessed by
        // the model. Do not turn estimate requests into made-up personal facts.
        bot('I don’t have a reliable basis to estimate your personal finances. Please give an amount you know, or leave it unknown; I won’t calculate a final answer from a guessed balance.');
        return;

      }
      if (before && current.current?.required && (message === SKIP || isDontKnow(message))) {
        current.current.targets.forEach(t => skipped.current.add(t));
        current.current = null;
        bot('I’ll leave that unknown. I won’t estimate your finances or give a final answer without the required facts.');
        await proceed(before); return;
      }
      // "Not sure" on an optional question just skips it, with no model call.
      if (before && current.current && !current.current.required && isDontKnow(message)) {
        for (const t of current.current.targets) skipped.current.add(t);
        current.current = null; bot('No problem, I’ll work without that.'); await proceed(before); return;
      }
      if (!before) {
        originalRef.current = message;
        const attempt = async () => {
          const result = await extraction.extract({ ...context(), ...withProfile(), user_message: message });
          if (consumePlainExtraction(result)) return;
          setExtraction(result); setStage(0); push({ role: 'bot', kind: 'understood', extraction: result });
          await proceed(result);
        };
        retry.current = async () => { setBusy(true); typing(); try { await attempt(); } catch { await failed(); } finally { setBusy(false); } };
        await attempt(); return;
      }
      const q = current.current;
      if (message === SKIP && q) {
        for (const t of q.targets) skipped.current.add(t);
        current.current = null;
        bot('No problem, I’ll work without that.'); await proceed(before); return;
      }
      const attempt = async () => {
        // A plain number answering a single question needs no model call.
        const target = q && q.targets.length === 1 ? before.assumptions.find(a => a.variable === q.targets[0]) : undefined;
        const local = target ? parseSimpleAnswer(message, target.unit) : null;
        const next = target && local !== null ? applyLocalAnswer(before, target.variable, local, message)
          : await extraction.correct({ ...context(), ...withProfile(), user_message: originalRef.current, previous_extraction: before, user_correction: q ? `Answering "${q.question}": ${message}` : plainQuestion.current ? `Answering "${plainQuestion.current}": ${message}` : message });
        if (consumePlainExtraction(next)) return;
        plainQuestion.current = null;
        const diff = changes(before, next);
        setExtraction(next); current.current = null;
        // A scoped approach has no registered extraction fields to diff, but
        // its conversation still contains meaningful corrections to calculate.
        if (!diff.length && !q && next.model) { bot('Thanks, I’ve noted that. Nothing I use in the numbers changed.'); return; }
        bot(diff.length ? `Got it. ${diff.join(' · ')}` : 'Thanks, I’ve noted that.');
        await proceed(next);
      };
      retry.current = async () => { setBusy(true); typing(); try { await attempt(); } catch { await failed(); } finally { setBusy(false); } };
      await attempt();
    } catch { await failed(); } finally { setBusy(false); }
  }

  // What-if: change a parameter, recalculate quietly, update the latest answer in place.
  const onParam = useCallback((key: string, value: string) => {
    paramsRef.current = { ...paramsRef.current, [key]: value }; setParams(paramsRef.current);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const value2 = exRef.current; if (!value2) return;
      const seq = ++calcSeq.current;
      try {
        const response = await calculator.calculate(request(originalRef.current, value2, paramsRef.current));
        if (seq !== calcSeq.current || (response.status !== 'ready' && response.status !== 'conditional')) return;
        setReviewedMath({ snapshot: value2, response });
        setMsgs(list => { const i = list.map(m => 'kind' in m && m.kind === 'answer').lastIndexOf(true); return i < 0 ? list : list.map((m, j) => j === i ? { ...m, response } as Msg : m); });
      } catch { /* keep the previous answer */ }
    }, 250);
  }, []);

  const reset = () => {
    if (timer.current) clearTimeout(timer.current);
    calcSeq.current++; idRef.current = 0; pendingUnknowns.current = null; exRef.current = null; originalRef.current = ''; plainQuestion.current = null; recoveryUsed.current = false; paramsRef.current = {}; asked.current = {}; skipped.current = new Set(); current.current = null; retry.current = null;
    setMsgs([]); setEx(null); setReviewedMath(null); setParams({}); setStage(0); setText(''); setBusy(false);
  };
  const pick = (value: string) => { setText(value); input.current?.focus(); };
  const lastAnswer = [...msgs].reverse().find(m => 'kind' in m && m.kind === 'answer') as Extract<Msg, { kind: 'answer' }> | undefined;
  const lastId = msgs.at(-1)?.id;
  const empty = msgs.length === 0;
  const saved = hasProfile(profile);
  const profileSummary = saved ? [profile.income !== undefined && `${money(profile.income)}/mo income`, monthlyExpenses(profile) !== undefined && `${money(monthlyExpenses(profile)!)}/mo spending`, profile.savings !== undefined && `${money(profile.savings)} saved`].filter(Boolean).join(' · ') : '';
  const profileButton = <button type="button" className={`${s.profileButton} ${saved ? s.profileSaved : ''}`} disabled={busy} onClick={() => setProfileOpen(true)} aria-label={saved ? 'Your profile' : 'Set up profile'} title={saved ? 'Your profile' : 'Set up profile'}>
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="8.5" r="3.6" /><path d="M4.8 19.5c1.3-3.4 4-5.2 7.2-5.2s5.9 1.8 7.2 5.2" /></svg>
    {saved && <span className={s.profileBadge} aria-hidden="true"><svg width="8" height="8" viewBox="0 0 10 10" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round"><path d="M2 5.2 4.2 7.4 8 2.8" /></svg></span>}
  </button>;
  const changeProfile = (p: Profile) => {
    profileRef.current = p; setProfile(p); setProfileOpen(false);
    if (exRef.current) bot(hasProfile(p) ? 'Profile saved. I’ll use it from your next message.' : 'Profile cleared. I won’t use it from your next message.');
  };
  // One composer: it sits in the home hero until the first message, then docks below the thread.
  const composer = <form className={`${s.composer} ${empty ? s.composerHero : ''}`} onSubmit={e => { e.preventDefault(); void send(text); }}>
    <textarea ref={input} rows={1} value={text} disabled={busy} placeholder={current.current ? 'Type your answer…' : ex ? 'Correct something or ask “what if…”' : 'Describe your goal and what you know…'}
      onChange={e => setText(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void send(text); } }} aria-label="Message" />
    <button type="submit" disabled={busy || !text.trim()}>Send</button>
  </form>;

  return <div className={s.page}>
    <header className={s.header}>
      <button type="button" className={s.brand} onClick={reset} aria-label="Start over"><Coin size={30} className={s.brandCoin} />Penny<span className={s.brandScript}>scope</span></button>
      <Status stage={stage} active={!empty} />
      <div className={s.headerRight}><button type="button" className={s.sheetToggle} onClick={() => setSheetOpen(o => !o)} aria-expanded={sheetOpen}>Working sheet</button><button type="button" className={s.newChat} onClick={reset}>New chat</button>{profileButton}</div>
    </header>
    <div className={s.body}>
      <main className={s.thread} aria-live="polite">
        {empty && <div className={s.welcome}><p className={s.kicker}>Can I afford it?</p><h1>What are you thinking about <span className={s.highlight}>buying or doing?</span></h1>
          <div className={s.heroAsk}><div className={s.mascot} aria-hidden="true"><span className={s.mascotBubble}>Rough numbers are fine!</span><Coin size={104} className={s.mascotCoin} /></div>{composer}</div>
          <section className={s.exampleSection} aria-labelledby="suggestions-heading"><h2 id="suggestions-heading" className={s.suggestionsHeading}>What you can ask</h2><div className={s.suggestions}>{SUGGESTIONS.map(t => <button key={t} type="button" onClick={() => pick(t)}>{t}</button>)}</div></section></div>}
        {msgs.map(m => m.role === 'user'
          ? <div key={m.id} className={`${s.row} ${s.user}`}><div className={s.bubbleUser}>{m.text}</div></div>
          : <div key={m.id} className={s.row}><span className={s.avatar} aria-hidden="true"><Coin size={38} /></span><div className={m.kind === 'answer' ? s.resultMessage : s.bubble}>
            {m.kind === 'typing' && <Typing />}
            {m.kind === 'text' && <><QuestionText text={m.text} verification={m.verification} />{m.note && <p className={s.note}>{m.note}</p>}
              {m.replies && m.id === lastId && <QuickReplies replies={m.replies} disabled={busy} onPick={send} />}</>}
            {m.kind === 'understood' && <Understood extraction={m.extraction} onPick={pick} />}
            {m.kind === 'answer' && <><PresentationBoundary resetKey={m.response} fallback={<PlainResult response={m.response} />}><AnswerCard response={m.response} interactive={m === lastAnswer} params={params} onParam={onParam} /></PresentationBoundary>
              <PresentationBoundary resetKey={m.response} fallback={null}><AnswerSupporting response={m.response} interactive={m === lastAnswer} disabled={busy} onAsk={send} /></PresentationBoundary></>}
          </div></div>)}
        <div ref={bottom} />
      </main>
      <div className={`${s.sheetWrap} ${sheetOpen ? s.sheetOpen : ''}`}><WorkingSheet extraction={ex} math={reviewedMath?.snapshot === ex ? reviewedMath?.response ?? null : null} profileSummary={profileSummary} onProfile={() => setProfileOpen(true)} /></div>
    </div>
    {!empty && composer}
    {profileOpen && <ProfilePanel profile={profile} onClose={() => setProfileOpen(false)}
      onSave={p => { saveProfile(p); changeProfile(p); }} onClear={() => { clearProfile(); changeProfile({}); }} />}
  </div>;
}
