# Model and factor selection refactor

Scope: routing, registry lookup, factor selection/extraction only. No calculator,
required-input engine, numeric normalization, Inspector or answer-generation logic
was replaced in this iteration. No UI layout/style files were changed.

## Inspected responsibility changes

The former extraction_service.py concatenated a savings-oriented base prompt and
several multi-model extensions. That single call selected a model, selected factors,
expressed derived quantities and sometimes suggested missing-input questions. Its
Bedrock wrapper added another set of extraction instructions.

That live combined prompt and its schema-repair loop were removed. The new path is:

1. model_router.route: one narrowly scoped LLM call; model_routing log stage.
2. extraction_service._extract_branch: validated route -> get_registry(model) in Python.
3. factor_selection.select: one narrowly scoped LLM call using only the selected
   registry and relevant state; factor_extraction log stage.
4. Python validates registry IDs, target, data shapes and envelope, merges retained
   supplied values, and adapts to the existing ExtractionResponse.

The router cannot extract factors or choose next actions. The factor response
cannot contain a model ID or next-stage instruction, use another model's factor
IDs, invent factor IDs, or calculate derived results. Neither call receives tools.
Unknown targets may be null; supplied facts are known, unsupplied relevant facts
are null/missing. An unsolved target is not a clarification question.

## Code boundaries

- routing_prompt.txt: the requested four definitions, examples and routing rules.
- model_router.py: strict routing output, including gap/ambiguous/multiple.
- factor_registry.py: four predefined Python registry objects with immutable
  factor definitions, supported targets, aliases and interpretation notes.
- factor_selection.py: selected-model prompt, constrained response schema and validation.
- extraction_service.py: execution order, correction/state handling and legacy envelope adapter.
- gemini_gateway.py / bedrock_transport.py: supplied stage-specific response schema
  and stage logs; provider retries/timeouts retained. Routing gets no factor/calculation
  wrapper instructions. Factor extraction gets no model-selection instructions.
- contract.py / main.py: optional history/profile inputs and forwarding; unresolved
  routing results stop before downstream calculation using existing response statuses.

Existing orchestration.py, dynamic_models.py, savings_model.py, financial_tools.py,
frontend components, bindings and response renderers are unchanged by this refactor.
The old root extraction.py notebook/reference artifact is not imported by the live path.

## State and unresolved routes

A concrete model selection is retained in selection_state. Ordinary explicit variable updates call only
factor extraction for that registry. Other follow-ups go to Router to distinguish continuation, new intent, or ambiguity. Existing effective
assumptions (including locally answered values) feed the next extraction. Earlier
known values omitted from a short correction are retained. Explicit supplied nulls
can clear previous values. History is retained up to twelve messages.

An unresolved route returns routing metadata with no selected model/factors:
- gap: existing unsupported response; no factor call or downstream calculation.
- ambiguous: a question about financial intent; no factor call.
- multiple: applicable IDs and a Python-composed question about which part to address.

A clarification of an unresolved route can run routing again. A clear new financial
intent reroutes and starts clean factors/history, even within the same model family.
Ambiguous transitions ask an intent question while retaining the active state; no
factor extraction runs until resolved.

## Registry coverage

The exact factor definitions/targets are in factor_registry.py. All requested factors
are present. Preserved additional existing identifiers are:
- budget: income_change (existing calculator scenario capability).
- savings aliases: monthly_spending, monthly_savings, months and target.
- bill aliases: total, people, method, tax, tip and weights.
- debt alias: balance -> principal_balance.

Aliases are accepted predefined IDs; they are not new generated factors. No factor
has a permanent input/output role. Entries/items/categories are JSON-array strings;
weights and amounts-paid/owed are JSON-object strings, preserving the current UI
value convention. Percent values retain their stated percentage (8% is 8, not .08).

## Explicit phase limits

This is two LLM calls for initial selection, not two calls for the entire existing
application. After selection, /calculate still uses the prior calculation/review
workflow, as requested. Its primary-calculation/Inspector behavior was not refactored.
The future deterministic missing-input stage has NOT been implemented here.
clarification_questions is therefore empty for concrete selection results; existing
downstream behavior remains responsible for financial clarifications for now.

Raw frequencies and dates are preserved. This phase does not annualize, compute
surplus, solve savings equations, allocate bills, or compute interest. Existing
calculator and formatter tests remain, and obsolete combined-extraction prompt
snapshot tests were replaced by tests for the actual two-stage runtime.

## Validation

Run from outer folder:
- .venv/bin/python -m unittest discover -s original_app/tests -p 'test_*.py'
- .venv/bin/python original_app/tests/python-extraction.py
- .venv/bin/python -m unittest test_agent_structure.py test_financial_tools.py

From original_app: npm test; npm run lint.

Tests cover exact execution order, all declared model targets, schema isolation,
unknown factors/targets, cross-model attempts, gap/ambiguous/multiple, raw frequency,
history/profile filtering, correction state, and real HTTP envelope compatibility.


## Recorded results

All four live Bedrock selection examples passed; abridged actual stage outputs are
saved in backend_reference/examples/selection-samples.json. The selected targets
remain null/missing, as this phase intentionally does not calculate them.

Initial selection has two logical LLM calls. A bounded pending-route cache keeps
an already validated route if factor extraction fails, so UI Retry resumes only
factor extraction. Entries expire after 30 minutes and are capped at 128; changed
question/context/profile/date uses a different key. A normal completed selection
removes its pending entry. Transport retries remain stage-local.

Python may materialize an empty display row for the explicitly selected target;
this is not an input requirement or a computed value. Format normalization is
limited to explicit method-label casing and literal representations such as
"five months" -> value 5 / unit months, or "$1,200" -> numeric 1200. No frequency,
percentage or financial arithmetic is performed; 8% stays 8, not 0.08.

The new selection path and existing backend tests pass (66 discovery tests plus
6 standalone extraction HTTP tests). The 25 original calculator tests, original
frontend suite including 800 render combinations, and lint pass. No production
financial calculators or downstream result generators were edited.


## Selection regression fixes

Generic monthly spending/income uses total factors; fixed/variable buckets and
entry tags require explicit category evidence. Regular timing alone is insufficient.
Known factors carry checked source evidence from user text, profile or retained
state. Numeric leaves (including structured values) must be supplied literals;
computed amounts, percentage conversions and fabricated amounts are rejected before
entering known state. Literal currency/count formatting remains supported. This is
a provenance guard, not a general semantic proof of every LLM interpretation.

Follow-up intent checks use the separate Router, followed by Python registry lookup;
ordinary explicit assignments use a deterministic continuation fast path. New intents
clear prior question factors/history. Ambiguous transitions preserve state and ask
clarification without invoking the extractor. Pending transition text is retained
when the user clarifies intent.

Actual Bedrock outputs are recorded in
backend_reference/examples/selection-fixes-runtime.json (four initial questions plus
budget-to-bill transition). All five passed. The budget returned monthly_spending
1650, raw biweekly income 900 without a fixed
category, and recurring_cost 90. The bill transition returned only total_bill 120,
participants 4, split_method equal and null amounts_owed; no computed 30 or old factors.

Validation after fixes: 74 backend discovery tests, 6 extraction HTTP tests,
25 original calculator/agent tests, frontend tests and lint passed.
Calculators, downstream orchestration/answer generation and UI were unchanged.


## Calculation targets in the UI

The backend target_variable and target factor rows remain unchanged in state.
The UI excludes the selected target from factor review chips, working-sheet rows,
result factor details, and missing-input questions. Null target rows are not user
inputs. Solved targets continue to appear in the existing answer headline/detail.
Known factors, genuinely missing inputs, source labels, styles, and binding indices
are preserved. No routing, extraction or financial calculation code changed.

Validation: frontend component/adapter tests cover all 17 supported targets from
the Python registry across the four models, including null and solved targets,
retained state and genuine missing inputs. Frontend tests, lint, production build,
and 74 backend discovery tests pass.
