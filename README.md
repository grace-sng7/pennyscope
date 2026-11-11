# Integrated original app

The approved LLM-first integration lives in `original_app/`. See
[original_app/INTEGRATION.md](original_app/INTEGRATION.md) for startup, architecture,
and tests. The original screens are at port 3000; the Gradio prototype below
remains separate at port 7860.

# Penny Scope: Travel Planner style Agent Prototype

## What is the same as the Human AI Travel Planner?
- `smolagents.CodeAgent` + `LiteLLMModel`
- `@tool` definitions with meaningful descriptions and args
- LLM chooses tools and passes known data to them; tool output informs `final_answer()`
- Optional Gradio chat UI, and terminal chat mode

## What is intentionally different?
- No web-search tools: this prototype uses an explicit financial model registry.
- Financial arithmetic lives in `financial_tools.py`, never the LLM.
- Instead of synchronous `user_input_tool`, the agent asks a clarification in its FINAL answer and continues when the next message comes in. This avoids blocking Gradio requests.
- Editable demo Financial Profile is OPTIONAL. No account integration or database.
- Fresh agent each turn with prior conversation included in context; real production state should be managed separately for scale/security.
- This does NOT automatically generate or validate new financial models. That is a later experiment recommended by Sherry.

## Run it

```bash
python -m pip install -r requirements.txt
# Paste your Google AI Studio API key into .secrets/gemini.json and save.
python agent_app.py --cli --trace
# Or:
python agent_app.py --web
```

Alternative LLMs can be selected through `MODEL_ID` and their required credentials (LiteLLM provider setup). Do not hardcode keys in source code.

## Run calculator tests without an LLM

```bash
python -m unittest discover -s . -p 'test_financial_tools.py' -v
python -m unittest test_agent_structure.py -v
```

## Prototype questions
1. I make $2,000 fixed and $300 in variable income each month. My fixed costs are $1,200 and variable costs are $700. Where can I save $100?
2. With $500 available savings and $400 monthly surplus, can I afford a $2,000 laptop in four months?
3. Three friends split a $120 dinner equally, but A already paid it. Who should pay whom?
4. Dinner was $120 but one person did not drink. Ask me who had which items before splitting.
5. I owe $2,000 at 24% APR. Compare paying $100, $200, or $300 monthly.

## Proofreading checklist
Check assumptions in `financial_tools.py` and `MODEL_REVIEW.md`. Particularly:
- available savings for THIS goal versus total account balance
- fixed/variable expense categories and flexibility; expense reduction is user-selected
- how shared items, tax, tip, or custom ratios are defined
- simple monthly APR debt assumption, not exact credit card statements

## Known limitations
- No official financial advice, bank connection, tax calculations, daily-balance credit card interest, variable APR, or comprehensive debt rules.
- Agent API calls incur provider costs. The tests do not prove agent reliability; run offline eval on actual user questions.
- `CodeAgent` evaluates generated action code in a constrained interpreter, but tools and prompts should still be reviewed before handling sensitive information.
- Not yet connected to your team's existing FastAPI endpoints or React UI.

The app loads `.secrets/gemini.json` automatically, using Gemini 2.5 Flash. Existing environment variables take priority. Bedrock settings are no longer loaded. Get a key at https://aistudio.google.com/apikey. The secrets folder is not encrypted; omit it when sharing this project.
