import type { CalculationResponse } from './calculation-contract';
import type { ExtractionResponse } from './extraction';
import type { Route } from './reasoning';

// Chat history. Like the profile, it is stored only in this browser (localStorage) and never sent anywhere.

export type Msg =
  | { id: number; role: 'user'; text: string }
  | { id: number; role: 'bot'; kind: 'text'; text: string; verification?: CalculationResponse['verification']; note?: string; replies?: string[]; route?: Route }
  | { id: number; role: 'bot'; kind: 'understood'; extraction: ExtractionResponse }
  | { id: number; role: 'bot'; kind: 'answer'; response: CalculationResponse }
  | { id: number; role: 'bot'; kind: 'typing' };

// Where the conversation stood, so a reopened chat carries on from the same place.
export interface ChatState {
  current: { targets: string[]; question: string; required: boolean } | null; // the question being waited on
  plainQuestion: string | null;          // a free-thinking follow-up question being waited on
  pendingUnknowns: string[] | null;      // required facts still unknown
  params: Record<string, string>;        // what-if values the user changed on the answer
  skipped: string[];                     // questions the user chose to skip, so they aren't asked again
  asked: Record<string, number>;         // how many times each question was asked (the chat stops after two)
}
export const emptyState = (): ChatState => ({ current: null, plainQuestion: null, pendingUnknowns: null, params: {}, skipped: [], asked: {} });

export interface ChatRecord {
  id: string;
  title: string;                          // the user's first message
  startedAt: number;                      // ms since epoch
  updatedAt: number;
  messages: Msg[];                        // never includes the typing indicator
  extraction: ExtractionResponse | null;  // the working sheet at the last save
  original: string;                       // the question the extraction came from
  state: ChatState;
}

const KEY = 'pennyscope-history-v1';
export const MAX_CHATS = 50;

export const newChatId = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;

const isRecord = (x: unknown): x is ChatRecord => {
  const r = x as ChatRecord;
  return !!r && typeof r.id === 'string' && typeof r.title === 'string' && typeof r.updatedAt === 'number' && Array.isArray(r.messages);
};

const readRaw = (): string | null => { try { return localStorage.getItem(KEY); } catch { return null; } };
function parse(raw: string | null): ChatRecord[] {
  try {
    const list = raw ? JSON.parse(raw) as unknown : [];
    return Array.isArray(list) ? list.filter(isRecord).map(r => ({ ...r, state: { ...emptyState(), ...r.state } })).sort((a, b) => b.updatedAt - a.updatedAt) : [];
  } catch { return []; }
}

// Newest first.
export function loadHistory(): ChatRecord[] { return parse(readRaw()); }

// For useSyncExternalStore: a cached snapshot that only changes when storage does,
// and a subscription to changes from this tab (writes below) and other tabs (storage event).
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(fn => fn());
let cachedRaw: string | null | undefined;
let cached: ChatRecord[] = [];
export function historySnapshot(): ChatRecord[] {
  const raw = readRaw();
  if (raw !== cachedRaw) { cachedRaw = raw; cached = parse(raw); }
  return cached;
}
export function subscribeHistory(fn: () => void): () => void {
  listeners.add(fn);
  const onStorage = (e: StorageEvent) => { if (e.key === KEY || e.key === null) fn(); };
  window.addEventListener('storage', onStorage);
  return () => { listeners.delete(fn); window.removeEventListener('storage', onStorage); };
}

function write(list: ChatRecord[]): void {
  // If the browser is out of space, drop the oldest chats until it fits (or nothing is left).
  for (let keep = list.length; keep >= 0; keep--) {
    try { localStorage.setItem(KEY, JSON.stringify(list.slice(0, keep))); notify(); return; } catch { /* quota or private mode: try smaller */ }
  }
}

// Build the record for a conversation. Returns null for a chat with nothing the user said yet.
export function toRecord(id: string, messages: Msg[], extraction: ExtractionResponse | null, original: string, startedAt: number, state: ChatState = emptyState(), now = Date.now()): ChatRecord | null {
  const kept = messages.filter(m => !('kind' in m && m.kind === 'typing'));
  const first = kept.find(m => m.role === 'user') as Extract<Msg, { role: 'user' }> | undefined;
  if (!first) return null;
  return { id, title: first.text.length > 120 ? `${first.text.slice(0, 117)}…` : first.text, startedAt, updatedAt: now, messages: kept, extraction, original, state };
}

// Pure: put a record at the front, replacing an older copy, and cap the list.
export function upsert(list: ChatRecord[], record: ChatRecord, max = MAX_CHATS): ChatRecord[] {
  return [record, ...list.filter(r => r.id !== record.id)].slice(0, max);
}

export function saveChat(record: ChatRecord): void { write(upsert(loadHistory(), record)); }
export function getChat(id: string): ChatRecord | undefined { return loadHistory().find(r => r.id === id); }
export function deleteChat(id: string): void { write(loadHistory().filter(r => r.id !== id)); }
export function clearHistory(): void { try { localStorage.removeItem(KEY); } catch { /* ignore */ } notify(); }

// The latest answer's headline, for the history list.
export function lastHeadline(r: ChatRecord): string | undefined {
  const answer = [...r.messages].reverse().find(m => 'kind' in m && m.kind === 'answer') as Extract<Msg, { kind: 'answer' }> | undefined;
  const res = answer?.response;
  return res && (res.status === 'ready' || res.status === 'conditional') ? res.answer.headline : undefined;
}

// Messages the user sent at the end of a chat that never got a reply (they left while the app was
// still answering). The reply is gone, so these are taken out of the thread and offered again.
function trailingUnanswered(messages: Msg[]): number {
  let i = messages.length;
  while (i > 0 && messages[i - 1].role === 'user') i--;
  return i;
}
export function unanswered(r: ChatRecord): string | null {
  const cut = trailingUnanswered(r.messages);
  const last = r.messages.at(-1);
  return cut < r.messages.length && last?.role === 'user' ? last.text : null;
}

// A saved chat, ready to continue. Unanswered messages at the end are left out (see above). Quick replies
// stay only on the last message, and only while its question is still open; anything else (e.g. "Try
// again" for a request that is gone) is dropped.
export function forResume(r: ChatRecord): Msg[] {
  const kept = r.messages.slice(0, trailingUnanswered(r.messages));
  const last = kept.at(-1)?.id;
  return kept.map(m => m.role === 'bot' && m.kind === 'text' && m.replies && !(r.state.current && m.id === last)
    ? (({ replies: _r, ...rest }) => { void _r; return rest; })(m) : m);
}
