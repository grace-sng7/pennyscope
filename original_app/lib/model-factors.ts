import type { AssumptionValue, ExtractionResponse, Source } from './extraction';

export type FinancialModel = 'budget_cash_flow' | 'savings_goal' | 'bill_split' | 'bill_custom' | 'bill_settlement' | 'debt_repayment';
export type FactorRole = 'known' | 'derived' | 'missing';
export interface ModelFactor {
  variable: string; value: AssumptionValue; unit: string | null; role: FactorRole;
  source: Source; source_detail: string; relevant?: boolean;
}
export interface ModelContext { model?: FinancialModel; target_variable?: string; factors?: ModelFactor[] }
export const ROLE_TITLES: Record<FactorRole, string> = { known: 'You Told Me', derived: 'I Worked Out', missing: 'Still Unknown' };
export const ROLE_SOURCE: Record<FactorRole, Source> = { known: 'stated', derived: 'inferred', missing: 'missing' };
const MODELS = ['budget_cash_flow', 'savings_goal', 'bill_split', 'bill_custom', 'bill_settlement', 'debt_repayment'];

// Optional metadata extends old responses; never infer roles from a variable's name.
export function validateModelContext(value: unknown): ModelContext {
  const fail = (): never => { throw new Error('Invalid financial factor metadata'); };
  if (!value || typeof value !== 'object' || Array.isArray(value)) return fail();
  const v = value as Record<string, unknown>;
  if (v.model != null && (typeof v.model !== 'string' || !MODELS.includes(v.model))) return fail();
  if (v.target_variable != null && (typeof v.target_variable !== 'string' || !v.target_variable.trim())) return fail();
  if (v.factors != null) {
    if (!Array.isArray(v.factors)) return fail();
    const seen = new Set<string>();
    for (const f of v.factors as ModelFactor[]) {
      if (!f || typeof f.variable !== 'string' || !f.variable.trim() || seen.has(f.variable) || !['known','derived','missing'].includes(f.role) || !['stated','inferred','missing'].includes(f.source) || typeof f.source_detail !== 'string' || !(f.unit === null || typeof f.unit === 'string') || !(f.value === null || typeof f.value === 'string' || typeof f.value === 'number' && Number.isFinite(f.value)) || f.relevant !== undefined && typeof f.relevant !== 'boolean') return fail();
      if ((f.value === null) !== (f.role === 'missing') || (f.value === null) !== (f.source === 'missing')) return fail();
      seen.add(f.variable);
    }
    if (v.target_variable && (!seen.has(v.target_variable as string) || (v.factors as ModelFactor[]).find(f => f.variable === v.target_variable)?.relevant === false)) return fail();
  }
  return { ...(v.model ? { model: v.model as FinancialModel } : {}), ...(v.target_variable ? { target_variable: v.target_variable as string } : {}), ...(v.factors != null ? { factors: structuredClone(v.factors) as ModelFactor[] } : {}) };
}

export function extractionFactors(extraction: ExtractionResponse): ModelFactor[] {
  const metadata = validateModelContext(extraction);
  return metadata.factors ?? extraction.assumptions.map(a => ({ ...a, role: a.source === 'stated' ? 'known' : a.source === 'inferred' ? 'derived' : 'missing' }));
}

// Targets stay in state, but are answered in response text rather than factor controls.
export function displayFactors(factors: ModelFactor[], target?: string): ModelFactor[] {
  return factors.filter(f => f.relevant !== false && f.variable !== target);
}

export function factorGroups(factors: ModelFactor[], target?: string) {
  return (['known', 'derived', 'missing'] as const).map(role => ({ role, title: ROLE_TITLES[role], source: ROLE_SOURCE[role], factors: displayFactors(factors, target).filter(f => f.role === role) })).filter(g => g.factors.length);
}
