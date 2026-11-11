import { extractionFactors } from './model-factors';
import type { ExtractionResponse } from './extraction';
import type { CalculationResponse } from './calculation-contract';
import { editingControl } from './field-values';
import { label } from './workspace-model';

// Lossless extraction-to-display projection, independent of calculation availability.
export function extractionInformation(raw: ExtractionResponse): CalculationResponse['information'] {
  return raw.assumptions.map((a, index) => ({
    presentation: a.variable === 'goal_description' ? 'detail' : undefined,
    id: `fact-${index}`, label: label(a.variable), value: a.value, unit: a.unit ?? '',
    binding: { kind: 'fact', index },
    control: { type: editingControl(a.value, a.unit) },
    source: a.source, sourceDetail: a.source_detail, confirmable: true,
  }));
}
export function presentResponse(raw: ExtractionResponse, response: CalculationResponse, changed = false): CalculationResponse {
  const target = response.target_variable ?? raw.target_variable;
  const covered = new Set(response.questions.flatMap(q => q.extractionQuestionIndices ?? []));
  const originals = raw.clarification_questions.flatMap((q, index) => covered.has(index) || q.target_variable === target ? [] : [{
    id: `extraction-question-${index}`, label: q.question, help: q.why_it_matters, unit: '', value: '',
    binding: { kind: 'answer' as const, key: `extraction-question-${index}` }, control: { type: 'text' as const }, required: false, extractionQuestionIndices: [index],
  }]);
  const information = extractionInformation(raw).map(field => {
    const metadata = response.information.find(f => f.binding.kind === 'fact' && field.binding.kind === 'fact' && f.binding.index === field.binding.index);
    const result = metadata ? { ...field, ...metadata, id: field.id, source: field.source, sourceDetail: field.sourceDetail } : field;
    return changed && field.source === 'inferred' ? { ...result, outdated: true, confirmable: false } : result;
  });
  const extras = response.information.filter(f => f.binding.kind !== 'fact' && !(f.binding.kind === 'answer' && f.binding.key === `input-${target}`)).map(f => ({ ...f, id: `calculation-${f.id}` }));
  const factors = response.factors ?? (raw.factors ? extractionFactors(raw) : undefined);
  const relevant = factors ? new Map(factors.filter(f => f.relevant !== false).map(f => [f.variable, f])) : null;
  const dynamicInformation = relevant ? information.flatMap(field => {
    const index = field.binding.kind === 'fact' ? field.binding.index : -1;
    const factor = relevant.get(raw.assumptions[index]?.variable);
    if (!factor || factor.variable === target) return [];
    return [{ ...field, role: factor.role, source: factor.source, sourceDetail: factor.source_detail,
      value: factor.value, unit: factor.unit ?? '', confirmable: factor.role === 'known',
      outdated: changed && factor.role === 'derived' }];
  }) : information.filter(field => field.binding.kind !== 'fact' || raw.assumptions[field.binding.index]?.variable !== target);
  const represented = new Set(dynamicInformation.map(f => f.binding.kind === 'fact' ? raw.assumptions[f.binding.index]?.variable : ''));
  const derivedInformation: CalculationResponse['information'] = factors ? factors.filter(f => f.relevant !== false && f.variable !== target && !represented.has(f.variable)).map(f => ({
    id: `model-${f.variable}`, label: label(f.variable), value: f.value, unit: f.unit ?? '',
    binding: { kind: 'answer', key: `input-${f.variable}` }, control: { type: 'text' },
    role: f.role, readOnly: true, source: f.source, sourceDetail: f.source_detail, confirmable: false,
    outdated: changed && f.role === 'derived',
  })) : [];
  const relevantOriginals = relevant ? originals.filter(q => {
    const index = q.extractionQuestionIndices?.[0];
    return index !== undefined && raw.clarification_questions[index].target_variable !== (response.target_variable ?? raw.target_variable) && relevant.get(raw.clarification_questions[index].target_variable)?.role === 'missing';
  }) : originals;
  return { ...response, information: [...dynamicInformation, ...extras, ...derivedInformation], questions: [...response.questions.map(q => ({ ...q, id: `calculation-${q.id}` })), ...relevantOriginals].sort((a, b) => Number(b.required) - Number(a.required)) };
}
