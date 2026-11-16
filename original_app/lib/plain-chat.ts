import type { CalculationResponse, Verification } from './calculation-contract';

export interface PlainChat { kind: 'answer' | 'question' | 'limitation'; text: string; verification?: Verification }
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);
export function parsePlainChat(value: unknown): PlainChat | null {
  if (!object(value) || !['answer', 'question', 'limitation'].includes(String(value.kind)) || typeof value.text !== 'string' || !value.text.trim()) return null;
  const verification = object(value.verification) && ['matched', 'mismatch', 'unverified', 'input_sufficient'].includes(String(value.verification.status)) ? value.verification as unknown as Verification : undefined;
  return { kind: value.kind as PlainChat['kind'], text: value.text, ...(verification ? { verification } : {}) };
}
export function plainFromResponse(value: unknown): PlainChat | null {
  if (!object(value)) return null;
  const existing = parsePlainChat(value.chat_fallback);
  if (existing) return existing;
  if ((value.status === 'ready' || value.status === 'conditional') && object(value.answer) && typeof value.answer.headline === 'string' && value.answer.headline.trim()) {
    const text = value.answer.headline + (typeof value.answer.detail === 'string' && value.answer.detail ? '\n' + value.answer.detail : '');
    const verification = object(value.verification) ? value.verification as unknown as Verification : { status: 'unverified' as const, target_variable: String(value.target_variable ?? 'chat_answer'), main_value: null };
    return { kind: 'answer', text, verification };
  }
  if (value.status === 'needs_input' && typeof value.message === 'string' && value.message.trim()) return { kind: 'question', text: value.message };
  return null;
}
export function chatCalculation(reply: PlainChat): CalculationResponse {
  const base = { information: [], questions: [], assumptions: [], parameters: [], metrics: [], explanations: [], limitations: [], nextActions: [], chat_fallback: reply, ...(reply.verification ? { verification: reply.verification } : {}) };
  return reply.kind === 'answer' ? { ...base, status: 'conditional', answer: { headline: reply.text } } : { ...base, status: 'needs_input', message: reply.text };
}
