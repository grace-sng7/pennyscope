"""Penny Scope: Travel Planner-style smolagents + tools + optional Gradio UI.

Usage:
    pip install -r requirements.txt
    # Add your Gemini API key to .secrets/gemini.json first.
    python agent_app.py --cli
    python agent_app.py --web

No user finances are saved to disk. The model provider receives conversation and
profile context; use fictional profiles for testing until privacy is reviewed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from financial_tools import (
    MODEL_REGISTRY,
    calculate_cash_flow,
    calculate_savings,
    split_bill,
    split_custom,
    settle_payments,
    calculate_debt_repayment,
    compare_debt_payments,
)

DEFAULT_PROFILE: dict[str, Any] = {
    "fixed_income": 2000,
    "variable_income": 300,
    "fixed_costs": 1200,
    "variable_costs": 700,
    "current_savings": 500,
    "currency": "USD",
}

SYSTEM_GUIDANCE = """You are Penny Scope, a student financial decision support assistant.
Follow this process for EACH user question:
1. Understand the decision; choose the applicable financial model(s).
2. Reuse numbers already supplied in the conversation or Financial Profile. The
   latest explicit user correction overrides older numbers and saved profile.
3. Decide what you need to know. If essential values or the user's split rule
   are missing, ask ONE short and relevant clarification in final_answer and STOP.
   Do not assume unknown numbers are zero. You may compute a clearly limited
   partial result if valid, while asking about the missing information.
4. Use the appropriate calculator tool for final numeric answers. NEVER use
   free-form model arithmetic instead of the deterministic tools.
5. Give the direct result FIRST, followed by key inputs and assumptions.
   When a savings/affordability target is not feasible, offer optional budgeting.
6. Do NOT give financial recommendations as commands. Let user control tradeoffs.

Model applicability:
- Budget/cash flow: fixed/variable income and fixed/variable costs; show
  monthly surplus; compare user-selected expense reductions. Do not label all
  variable costs unnecessary. If user has only income/spending totals, use them.
- Savings/purchase: SAME MODEL; S_future = S_available + M*N;
  M = monthly income - monthly spending if no monthly savings given.
  current_savings means money available for THIS goal, NOT all bank funds.
  If profile savings are not explicitly available for a particular goal, ask
  for confirmation before spending them. For a purchase NOW, months=0.
- Bill splitting: highly scenario-dependent. Ask about people, shared items,
  proportional rules, tax/tip, and who already paid when relevant. Do not
  force a method when the user wants an uncommon custom split. Once a clear
  rule is agreed, use equal/itemized/weighted arithmetic tools; then optionally
  settle transfers from amounts owed and already paid. Never invent recipients.
- Debt/credit card: compare monthly payments or payoff durations. APR is
  annual percentage. Model assumes fixed APR, once-monthly interest and
  payments, no fees or new spending. Card grace periods/daily accrual differ.

Do not invoke tools with made-up values. Do not perform web search. Explicitly
state when the available profile is incomplete. Only reuse a historical number
when its meaning and time period match the current question.
"""


def encode(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def parse_payload(payload: str) -> dict[str, Any]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Payload must be a JSON object")
    return data


def tool_response(name: str, payload: str, calculator, trace: list[dict]) -> str:
    """Validate JSON, run deterministic code, log values for proofreading."""
    try:
        args = parse_payload(payload)
        result = calculator(**args)
        trace.append({"tool": name, "inputs": args, "output": result})
        return encode({"ok": True, "result": result})
    except (TypeError, ValueError, KeyError, ArithmeticError) as exc:
        err = {"ok": False, "error": str(exc)}
        trace.append({"tool": name, "inputs": payload, "output": err})
        return encode(err)


def build_tools(profile: dict[str, Any], trace: list[dict]):
    """@tool wrappers parallel those in the Human AI Travel Planner."""
    from smolagents import tool

    @tool
    def read_financial_profile() -> str:
        """Read the known financial profile. Missing fields mean UNKNOWN, not zero.

        Returns:
            JSON profile fields and derived context. Never request login data.
        """
        trace.append({"tool": "read_financial_profile", "inputs": {}, "output": profile})
        return encode({"profile": profile, "missing_means_unknown": True})

    @tool
    def budget_cash_flow(payload: str) -> str:
        """Calculate monthly budget and cash flow; optionally explore expense savings.

        Args:
            payload: JSON object. Choose ONE income source: monthly_income,
                income_entries=[{amount,frequency,category:'fixed'|'variable'}],
                OR fixed_income+variable_income. Choose ONE spending source:
                monthly_spending, spending_entries, OR fixed_costs+variable_costs.
                Optional income_change, spending_change are MONTHLY signed deltas.
                Optional expense_categories=[{name,amount,frequency?,flexibility:
                'essential'|'adjustable'|'discretionary',proposed_reduction?}].
                A full category breakdown must equal total spending; selected
                reductions are user choices, not agent assumptions. Do not mix
                aggregate sources with detailed source fields in one call.
        """
        return tool_response("budget_cash_flow", payload, calculate_cash_flow, trace)

    @tool
    def savings_projection(payload: str) -> str:
        """Answer purchase affordability OR savings goal using one shared model.

        Args:
            payload: JSON object with solve_for one of future_balance,
                affordability, monthly_required, months_required. Possible keys:
                current_savings (available for THIS goal), monthly_savings,
                months (nonnegative integer), target, monthly_income,
                monthly_spending. Monthly savings = income - spending when both
                supplied. Do not supply both monthly_savings and income/spending.
                affordabilty requires target/months and savings rate; a purchase
                today uses months=0. monthly_required needs target/months;
                months_required needs target and positive monthly savings.
                Avoid default current_savings=0 unless genuinely zero or user
                explicitly wants a zero-savings illustration.
        """
        return tool_response("savings_projection", payload, calculate_savings, trace)

    @tool
    def bill_split(payload: str) -> str:
        """Split a bill equally or by item; clarify customized dining rules FIRST.

        Args:
            payload: JSON object with method='equal' or 'itemized', people as
                list of unique names. For equal, total includes all tax/tip.
                For itemized, items=[{amount,shared_by:[person,...]}], optionally
                tax, tip and total for verification. Tax/tip are prorated against
                item amounts; only use when user agrees to this rule.
        """
        return tool_response("bill_split", payload, split_bill, trace)

    @tool
    def bill_split_custom(payload: str) -> str:
        """Divide a known bill using user-approved custom relative weights.

        Args:
            payload: JSON object {"total":120,"weights":{"A":2,"B":1}}.
                Weights are nonnegative and can represent any agreed ratios.
                Clarify the rule if the users have not specified allocation.
        """
        return tool_response("bill_split_custom", payload, split_custom, trace)

    @tool
    def bill_settlement(payload: str) -> str:
        """Find who transfers to whom AFTER each person's owed share is known.

        Args:
            payload: JSON object {"amounts_owed":{"A":40,"B":40},
                "amounts_paid":{"A":80,"B":0}}. Same people and same
                total must appear in both objects. Paid means money already
                paid toward this bill. If unclear, ask a clarification.
        """
        return tool_response("bill_settlement", payload, settle_payments, trace)

    @tool
    def debt_repayment(payload: str) -> str:
        """Calculate monthly loan/card interest, payoff time, or needed payment.

        Args:
            payload: JSON object with balance, apr as a PERCENT (24 means 24%),
                and ONE of monthly_payment or payoff_months; neither returns
                the first-month interest estimate. Constant APR/monthly interest.
                For desired payoff timeline use payoff_months, not monthly_payment.
        """
        return tool_response("debt_repayment", payload, calculate_debt_repayment, trace)

    @tool
    def debt_compare(payload: str) -> str:
        """Compare credit card/loan repayment choices and total interest cost.

        Args:
            payload: JSON object with balance, apr (annual percent), and
                EITHER monthly_payments=[100,200,300] OR
                payoff_months_options=[6,12,24]. Returns payoff duration,
                interest, and total repayment for each option.
        """
        return tool_response("debt_compare", payload, compare_debt_payments, trace)

    return [read_financial_profile, budget_cash_flow, savings_projection,
            bill_split, bill_split_custom, bill_settlement,
            debt_repayment, debt_compare]


def build_agent(profile: dict[str, Any], trace: list[dict]):
    load_local_gemini_settings()
    from smolagents import CodeAgent, LiteLLMModel
    import litellm

    litellm.drop_params = True
    model_id = os.environ.get("MODEL_ID", "gemini/gemini-2.5-flash")
    model = LiteLLMModel(model_id=model_id)
    return CodeAgent(
        model=model,
        tools=build_tools(profile, trace),
        max_steps=10,
        verbosity_level=1,
    )


def load_local_gemini_settings():
    """Load optional local credentials without logging their contents."""
    path = Path(__file__).resolve().parent / ".secrets" / "gemini.json"
    if not path.exists():
        return
    try:
        settings = json.loads(path.read_text())
        if not isinstance(settings, dict):
            raise ValueError()
        for key in ("api_key", "model_id"):
            if key in settings and not isinstance(settings[key], str):
                raise ValueError()
    except (OSError, ValueError):
        raise ValueError(
            "Cannot read .secrets/gemini.json. Keep the original JSON format "
            "and put each value inside double quotes."
        ) from None
    for field, variable in (
        ("api_key", "GEMINI_API_KEY"),
        ("model_id", "MODEL_ID"),
    ):
        value = settings.get(field, "").strip()
        if value:
            os.environ.setdefault(variable, value)


def get_answer(message: str, history: list[dict], profile: dict[str, Any],
               show_trace: bool = False) -> str:
    trace: list[dict] = []
    agent = build_agent(profile, trace)
    # A fresh agent per turn avoids cross-user shared state; supply conversational
    # history explicitly to retain answers to earlier clarification questions.
    brief_history = history[-12:]
    task = (
        SYSTEM_GUIDANCE
        + "\nFinancial model registry:\n" + encode(MODEL_REGISTRY)
        + "\nFinancial Profile snapshot (may contain unknown fields):\n" + encode(profile)
        + "\nConversation so far (earliest to latest):\n" + encode(brief_history)
        + "\nCurrent user question:\n" + message
        + "\nReturn a concise answer by calling final_answer()."
    )
    response = str(agent.run(task))
    if show_trace:
        response += "\n\nCalculator tool trace:\n```json\n" + encode(trace) + "\n```"
    return response


def profile_from_json(text: str) -> dict[str, Any]:
    if not text.strip():
        return {}
    obj = json.loads(text)
    if not isinstance(obj, dict):
        raise ValueError("Profile must be a JSON object")
    return {key: val for key, val in obj.items() if val is not None}


def cli(profile: dict[str, Any], show_trace: bool):
    print("Penny Scope CLI. Enter /exit to quit, /profile to view profile.")
    history: list[dict] = []
    while True:
        try:
            message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye")
            break
        if message.lower() in ("/exit", "/quit"):
            break
        if message == "/profile":
            print(encode(profile))
            continue
        if not message:
            continue
        try:
            response = get_answer(message, history, profile, show_trace)
        except Exception as exc:
            print(f"Agent error: {exc}")
            continue
        print("Penny Scope:", response)
        history.extend([{"role": "user", "content": message},
                        {"role": "assistant", "content": response}])


def web(profile: dict[str, Any]):
    import gradio as gr
    import inspect
    # Gradio 6 always uses messages; Gradio 5 requires this option explicitly.
    chat_options = {"height": 500}
    if "type" in inspect.signature(gr.Chatbot).parameters:
        chat_options["type"] = "messages"
    with gr.Blocks(title="Penny Scope Agent Prototype") as demo:
        gr.Markdown("# Penny Scope | Agent Prototype\nText in, text out. Four financial models, with inspectable tool calls.")
        with gr.Row():
            with gr.Column(scale=3):
                chat = gr.Chatbot(**chat_options)
                message = gr.Textbox(label="Your financial question", placeholder="Can I save $3,000 in six months?", lines=2)
                with gr.Row():
                    send = gr.Button("Send", variant="primary")
                    clear = gr.Button("Clear chat")
            with gr.Column(scale=2):
                profile_text = gr.Code(value=encode(profile), language="json", label="Editable demo Financial Profile", lines=13)
                show_trace = gr.Checkbox(label="Show calculator tool inputs and outputs", value=True)
                gr.Markdown("Missing fields are unknown. Use fictional data for testing; profile is sent to the model provider.")
        def respond(user_text, chat_history, profile_str, trace_on):
            h = list(chat_history or [])
            try:
                p = profile_from_json(profile_str)
                previous = h[:]  # do not include current message twice
                answer = get_answer(user_text, previous, p, trace_on)
            except Exception as exc:
                answer = f"Error: {exc}"
            h += [{"role": "user", "content": user_text},
                  {"role": "assistant", "content": answer}]
            return h, ""
        send.click(respond, [message,chat,profile_text,show_trace],[chat,message])
        message.submit(respond,[message,chat,profile_text,show_trace],[chat,message])
        clear.click(lambda: [], outputs=chat)
    demo.launch()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", action="store_true", help="Terminal chat instead of Gradio")
    parser.add_argument("--web", action="store_true", help="Open Gradio UI")
    parser.add_argument("--empty-profile", action="store_true", help="Do not use demo data")
    parser.add_argument("--profile", type=Path, help="Path to a JSON profile file")
    parser.add_argument("--trace", action="store_true", help="Print tool traces in CLI")
    args = parser.parse_args()
    profile = {} if args.empty_profile else DEFAULT_PROFILE.copy()
    if args.profile:
        profile = profile_from_json(args.profile.read_text())
    if args.web:
        web(profile)
    else:
        cli(profile, args.trace)


if __name__ == "__main__":
    main()
