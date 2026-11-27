import assert from 'node:assert/strict';
import { toRecord, upsert, forResume, lastHeadline, loadHistory, saveChat, deleteChat, getChat, clearHistory, MAX_CHATS } from '../lib/history.ts';

// A tiny in-memory localStorage.
const store = new Map();
globalThis.localStorage = { getItem: k => store.get(k) ?? null, setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) };

const msgs = [
  { id: 1, role: 'user', text: 'Can I afford a $900 laptop?' },
  { id: 2, role: 'bot', kind: 'text', text: 'How much do you make?', replies: ['Not sure, skip this'] },
  { id: 3, role: 'bot', kind: 'typing' },
];
assert.equal(toRecord('a', [], null, '', 1), null, 'nothing said yet: not saved');
assert.equal(toRecord('a', [{ id: 1, role: 'bot', kind: 'typing' }], null, '', 1), null);
const r = toRecord('a', msgs, null, 'Can I afford a $900 laptop?', 1, undefined, 5);
assert.equal(r.title, 'Can I afford a $900 laptop?');
assert.equal(r.messages.length, 2, 'typing indicator dropped');
assert.deepEqual([r.startedAt, r.updatedAt], [1, 5]);
assert.ok(toRecord('b', [{ id: 1, role: 'user', text: 'x'.repeat(300) }], null, '', 1).title.length <= 120, 'long titles trimmed');

// upsert: newest first, replaces the old copy, capped.
let list = upsert([], r);
list = upsert(list, { ...r, id: 'b' });
list = upsert(list, { ...r, updatedAt: 9 });
assert.deepEqual(list.map(x => x.id), ['a', 'b']);
assert.equal(list[0].updatedAt, 9);
let many = [];
for (let i = 0; i < MAX_CHATS + 5; i++) many = upsert(many, { ...r, id: `c${i}` });
assert.equal(many.length, MAX_CHATS);
assert.equal(many[0].id, `c${MAX_CHATS + 4}`);

// Resuming drops stale quick replies, nothing else.
const resumed = forResume(r);
assert.equal(resumed[1].replies, undefined);
assert.equal(resumed[1].text, 'How much do you make?');
assert.deepEqual(r.messages[1].replies, ['Not sure, skip this'], 'saved record not mutated');
// ...but kept on the last message while its question is still pending.
const pending = { targets: ['monthly_income'], question: 'How much do you make?', required: true };
const waiting = toRecord('a', msgs, null, 'q', 1, { current: pending, plainQuestion: null, pendingUnknowns: null, params: { monthly_contribution: '300' }, skipped: ['monthly_income'], asked: { monthly_income: 2 } }, 5);
assert.deepEqual(waiting.state.current, pending);
assert.deepEqual(waiting.state.params, { monthly_contribution: '300' });
assert.deepEqual([waiting.state.skipped, waiting.state.asked], [['monthly_income'], { monthly_income: 2 }], 'skipped questions and ask counts are kept');
saveChat(waiting);
assert.deepEqual(getChat('a').state.skipped, ['monthly_income'], 'and survive a round trip');
clearHistory();
assert.deepEqual(forResume(waiting)[1].replies, ['Not sure, skip this']);
assert.equal(forResume({ ...waiting, messages: [...waiting.messages, { id: 9, role: 'user', text: 'hi' }] })[1].replies, undefined, 'not on an earlier message');

// Headline of the latest ready answer.
assert.equal(lastHeadline(r), undefined);
const answered = { ...r, messages: [...r.messages, { id: 4, role: 'bot', kind: 'answer', response: { status: 'ready', answer: { headline: 'Yes, by March.' } } }] };
assert.equal(lastHeadline(answered), 'Yes, by March.');

// Storage round trip, newest first; corrupt storage reads as empty.
saveChat({ ...r, id: 'old', updatedAt: 1 });
saveChat({ ...r, id: 'new', updatedAt: 2 });
assert.deepEqual(loadHistory().map(x => x.id), ['new', 'old']);
assert.equal(getChat('old').id, 'old');
deleteChat('old');
assert.deepEqual(loadHistory().map(x => x.id), ['new']);
clearHistory();
assert.deepEqual(loadHistory(), []);
store.set('pennyscope-history-v1', '{not json');
assert.deepEqual(loadHistory(), []);
store.set('pennyscope-history-v1', JSON.stringify([{ junk: true }, { ...r, id: 'ok' }]));
assert.deepEqual(loadHistory().map(x => x.id), ['ok'], 'malformed entries skipped');
// A record saved without state still loads with an empty one.
const { state: _s, ...noState } = r; void _s;
store.set('pennyscope-history-v1', JSON.stringify([noState]));
assert.deepEqual(loadHistory()[0].state, { current: null, plainQuestion: null, pendingUnknowns: null, params: {}, skipped: [], asked: {} });
// An older record without the newer fields gets them filled in.
store.set('pennyscope-history-v1', JSON.stringify([{ ...r, state: { current: null, plainQuestion: null, pendingUnknowns: null, params: {} } }]));
assert.deepEqual([loadHistory()[0].state.skipped, loadHistory()[0].state.asked], [[], {}]);

// Out of space: oldest chats are dropped until it fits.
clearHistory();
const realSet = globalThis.localStorage.setItem;
globalThis.localStorage.setItem = (k, v) => { if (JSON.parse(v).length > 2) throw new Error('QuotaExceeded'); realSet(k, v); };
store.set('pennyscope-history-v1', JSON.stringify([{ ...r, id: 'x2', updatedAt: 2 }, { ...r, id: 'x1', updatedAt: 1 }]));
saveChat({ ...r, id: 'x3', updatedAt: 3 });
assert.deepEqual(loadHistory().map(x => x.id), ['x3', 'x2']);

console.log('PASS: history records, chat state, upsert cap, resume, headline, storage round trip, corrupt data and quota');
