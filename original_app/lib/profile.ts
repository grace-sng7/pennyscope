// "Your profile": a few basic facts the user saves once so the chat doesn't have to ask every time.
// Stored only in this browser (localStorage). When set, the figures are sent with each extract/correct
// request as `financial_profile`; the backend treats them as evidence, and anything said in the chat wins.
export interface Profile {
  income?: number;         // monthly, after tax
  rent?: number;           // monthly
  otherExpenses?: number;  // monthly, everything besides rent
  savings?: number;
}

const KEY = 'pennyscope-profile-v1';
const num = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0;

export function loadProfile(): Profile {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? '{}') as Record<string, unknown>;
    const p: Profile = {};
    for (const k of ['income', 'rent', 'otherExpenses', 'savings'] as const) if (num(raw[k])) p[k] = raw[k] as number;
    return p;
  } catch { return {}; }
}
export function saveProfile(p: Profile): void {
  try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* private mode: the profile lasts this session only */ }
}
export function clearProfile(): void {
  try { localStorage.removeItem(KEY); } catch { /* ignore */ }
}

export const hasProfile = (p: Profile) => [p.income, p.rent, p.otherExpenses, p.savings].some(num);
export const monthlyExpenses = (p: Profile) => num(p.rent) || num(p.otherExpenses) ? (p.rent ?? 0) + (p.otherExpenses ?? 0) : undefined;

// Keys match the backend factor registries; the server keeps only the ones the chosen model uses.
export function financialProfile(p: Profile): Record<string, number> | undefined {
  const out: Record<string, number> = {};
  if (num(p.income)) out.monthly_income = p.income;
  const expenses = monthlyExpenses(p);
  if (expenses !== undefined) out.monthly_expenses = expenses;
  if (num(p.savings)) out.current_savings = p.savings;
  return Object.keys(out).length ? out : undefined;
}

// The backend marks a value it took from the profile with evidence.source === 'profile'.
export const fromProfile = (f: unknown): boolean => {
  const evidence = (f as { evidence?: unknown } | null)?.evidence;
  return !!evidence && typeof evidence === 'object' && (evidence as { source?: unknown }).source === 'profile';
};
