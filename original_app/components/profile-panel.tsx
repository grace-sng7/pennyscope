'use client';
// "Your profile": a few basic facts saved once so the chat doesn't have to ask each time.
import { useEffect, useRef, useState } from 'react';
import type { Profile } from '../lib/profile';
import s from '../app/chat/chat.module.css';

type Field = 'income' | 'rent' | 'otherExpenses' | 'savings';
const FIELDS: [Field, string, string][] = [
  ['income', 'Monthly income', 'After tax, from all sources'],
  ['rent', 'Monthly rent', 'Including utilities, if you pay them'],
  ['otherExpenses', 'Other monthly spending', 'Food, phone, transport, subscriptions…'],
  ['savings', 'Current savings', 'Optional'],
];

export function ProfilePanel({ profile, onSave, onClear, onClose }: { profile: Profile; onSave: (p: Profile) => void; onClear: () => void; onClose: () => void }) {
  const [draft, setDraft] = useState<Profile>(profile);
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => {
    first.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const setNum = (k: Field, v: string) => setDraft(d => ({ ...d, [k]: v.trim() === '' || !Number.isFinite(Number(v)) || Number(v) < 0 ? undefined : Number(v) }));
  return <div className={s.overlay} onClick={onClose}>
    <form className={s.profile} role="dialog" aria-modal="true" aria-labelledby="profile-title" onClick={e => e.stopPropagation()} onSubmit={e => { e.preventDefault(); onSave(draft); }}>
      <h2 id="profile-title">Your profile</h2>
      <p className={s.muted}>Fill in what you’re comfortable with. I’ll use it instead of asking, and anything you say in a chat overrides it.</p>
      <div className={s.profileFields}>
        {FIELDS.map(([k, title, hint], i) => <label key={k}><span>{title}</span>
          <span className={s.moneyInput}><span aria-hidden="true">$</span><input ref={i === 0 ? first : undefined} type="number" inputMode="decimal" min={0} step="any" value={draft[k] ?? ''} onChange={e => setNum(k, e.target.value)} aria-describedby={`${k}-hint`} /></span>
          <small id={`${k}-hint`} className={s.muted}>{hint}</small></label>)}
      </div>
      <p className={s.privacy}>Saved only in this browser. Each time you ask a question, these figures are sent along with it to the assistant and its AI model so they can be used in your answer.</p>
      <div className={s.profileActions}>
        <button type="button" onClick={() => { onClear(); setDraft({}); }}>Clear profile</button>
        <span />
        <button type="button" onClick={onClose}>Cancel</button>
        <button type="submit" className={s.primary}>Save</button>
      </div>
    </form>
  </div>;
}
