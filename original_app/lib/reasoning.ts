// How the backend reached an answer: which model it matched (or free thinking),
// the inputs it used and where each came from, and the worked steps in order.
// Display only: nothing here changes a number.

export interface Route { path: 'model' | 'free'; model: string; title: string; reason: string }
export interface ReasoningInput { variable: string; value: unknown; unit: string | null; how: 'stated' | 'inferred' | 'profile'; note: string }
export interface ReasoningStep { label: string; formula: string; work: string; result: string }
export interface Reasoning { route: Route; assumptions: ReasoningInput[]; steps: ReasoningStep[]; notes: string[] }

const obj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown) => (typeof v === 'string' ? v : '');

export function readRoute(v: unknown): Route | undefined {
  if (!obj(v) || (v.path !== 'model' && v.path !== 'free') || !str(v.title)) return;
  return { path: v.path, model: str(v.model), title: str(v.title), reason: str(v.reason) };
}

export function readReasoning(v: unknown): Reasoning | undefined {
  if (!obj(v)) return;
  const route = readRoute(v.route);
  if (!route) return;
  const assumptions = (Array.isArray(v.assumptions) ? v.assumptions : []).filter(obj).filter(a => str(a.variable)).map(a => ({
    variable: str(a.variable), value: a.value, unit: typeof a.unit === 'string' ? a.unit : null,
    how: (['stated', 'inferred', 'profile'].includes(String(a.how)) ? a.how : 'stated') as ReasoningInput['how'], note: str(a.note),
  }));
  const steps = (Array.isArray(v.steps) ? v.steps : []).filter(obj).filter(s => str(s.label) && str(s.result))
    .map(s => ({ label: str(s.label), formula: str(s.formula), work: str(s.work), result: str(s.result) }));
  const notes = (Array.isArray(v.notes) ? v.notes : []).filter((n): n is string => typeof n === 'string' && !!n.trim());
  return { route, assumptions, steps, notes };
}
