import type { Verification } from '../lib/calculation-contract';

export function VerificationWarning({ verification }: { verification?: Verification }) {
  if (!verification) return null;
  const show = verification.context === 'question'
    ? verification.status === 'input_sufficient'
    : verification.status === 'mismatch' || verification.status === 'unverified';
  if (!show) return null;
  const message = verification.message ?? 'The independent check could not confirm this answer. Main’s answer is shown.';
  return <span role="img" aria-label={message} title={message} tabIndex={0} data-verification-warning={verification.status}
    style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 16, height: 16, marginInlineStart: 8, border: '1px solid currentColor', borderRadius: '50%', fontSize: 11, lineHeight: 1, verticalAlign: 'middle' }}>!</span>;
}
