// Real network services. They call the Next.js proxy (app/api/backend/[action]) which forwards
// to the Python backend at BACKEND_URL. Nothing here knows any financial logic.
import { TransportExtractionService, type CorrectionRequest, type ExtractRequest } from './extraction';
import { type CalculationRequest, type CalculationResponse, type CalculationService } from './calculation-contract';
import { chatCalculation, parsePlainChat, plainFromResponse, type PlainChat } from './plain-chat';
import { fromCalculateWire, toCalculateWire } from './backend-wire';
import { validateModelContext } from './model-factors';

type Fetch = (input: string, init?: RequestInit) => Promise<Response>;
const FRIENDLY: Record<string, string> = { extract: 'We couldn’t review your description right now. Please retry.', correct: 'We couldn’t apply your corrections right now. Your edits are kept — please retry.', calculate: 'Calculation unavailable.', 'chat-fallback': 'Plain language response unavailable.' };

export async function postJson(action: 'extract' | 'correct' | 'calculate' | 'chat-fallback', body: unknown, fetchImpl: Fetch = (i, init) => fetch(i, init), base = '/api/backend'): Promise<unknown> {
  let response: Response;
  try {
    response = await fetchImpl(`${base}/${action}`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(420_000) });
  } catch {
    throw new Error(`${FRIENDLY[action]} (could not reach the server)`);
  }
  let payload: unknown = null;
  try { payload = await response.json(); } catch { /* non-JSON body */ }
  if (!response.ok) {
    const detail = payload && typeof payload === 'object' && 'detail' in payload ? (payload as { detail: unknown }).detail : undefined;
    console.error(`[backend] ${action} failed`, response.status, detail);
    throw new Error(`${FRIENDLY[action]}${typeof detail === 'string' ? ` (${detail})` : ` (status ${response.status})`}`);
  }
  return payload;
}

export class HttpCalculationService implements CalculationService {
  constructor(private readonly fetchImpl?: Fetch, private readonly base?: string) {}
  async calculate(request: CalculationRequest): Promise<CalculationResponse> {
    const raw = await postJson('calculate', toCalculateWire(request), this.fetchImpl, this.base);
    const plain = plainFromResponse(raw);
    if (raw && typeof raw === 'object' && 'chat_fallback' in raw && parsePlainChat(raw.chat_fallback) && plain) {
      const response = chatCalculation(plain);
      try { Object.assign(response, validateModelContext(raw)); } catch { /* Plain answer survives invalid card metadata. */ }
      return response;
    }
    try { return fromCalculateWire(raw, request); } catch (error) {
      if (plain) return chatCalculation(plain);
      throw error;
    }
  }
}

export const liveExtractionService = new TransportExtractionService({
  extract: (r: ExtractRequest) => postJson('extract', r),
  correct: (r: CorrectionRequest) => postJson('correct', r),
});
export const liveCalculationService: CalculationService = new HttpCalculationService();


export async function recoverPlainChat(user_message: string, confirmed_facts: unknown[], user_correction?: string): Promise<PlainChat> {
  try {
    const raw = await postJson('chat-fallback', { user_message, confirmed_facts, user_correction });
    const reply = parsePlainChat(raw);
    if (reply) return reply;
  } catch { /* Keep the user's information visible even during a transport outage. */ }
  const facts = confirmed_facts.filter((a): a is { variable: string; value: string | number } => !!a && typeof a === 'object' && 'variable' in a && 'value' in a && a.value != null);
  return { kind: 'limitation', text: (facts.length ? 'Here is what I retained:\n' + facts.map(a => `${a.variable.replaceAll('_', ' ')}: ${a.value}`).join('\n') : 'I retained your question:\n' + user_message) + '\nI could not complete the requested calculation in this attempt. Your information is kept.' };
}
