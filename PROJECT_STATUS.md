# Penny Scope snapshot — November 10, 2026

The working application is in original_app/. The shared financial calculators
are in financial_tools.py at the repository root. The root agent_app.py is the
earlier separate prototype.

## Implemented

- Separate Model Router and registry-specific Factor Extraction calls.
- Four predefined model registries and dynamic factor roles.
- Evidence validation, new-intent routing, and correction-state preservation.
- Main LLM primary calculation, independent Python verification, Inspector review.
- Target factors retained in state and excluded from editable/missing-input UI.
- Provider support and bounded transient stage retries.

See original_app/SELECTION_WORKFLOW.md, original_app/UI_FACTOR_PLAN.md and
original_app/INTEGRATION.md for implementation details and recorded validation.

## Known gaps from the read-only audit

- Extraction and Main overlap in model/target interpretation.
- Raw weekly savings contributions have no savings-specific conversion adapter,
  despite the shared monthly() utility already supporting periodic amounts.
- Currency review chips omit some frequency suffixes, including weekly.
- Bedrock Main can return malformed JSON; parsing failure surfaces as HTTP 502.
- Target-specific missing-input detection is still primarily LLM-driven.

## Proposed handoff — not implemented

Router proposes the model; Factor Extraction selects relevant facts and target.
Main independently evaluates the handoff while retaining primary calculation.
On disagreement Python should allow one bounded reevaluation using existing
stages and supported definitions/targets. A changed model or target requires
fresh registry-specific extraction using retained original evidence/corrections.
Unresolved disagreement requires user clarification. Model, target, solver mode,
bindings and units must be consistent before independent Python verification.
No unconditional additional LLM call is proposed.

This proposal was discussed but has not been implemented or tested.

## Private local configuration

.secrets/, .env files, the virtual environment, node_modules, build products and
machine-specific credentials are excluded from version control. A fresh checkout
needs its own local credentials and dependencies. No credentials are included.
