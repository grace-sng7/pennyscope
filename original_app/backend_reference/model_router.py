"""LLM call 1: model ID only. Python owns the subsequent transition."""
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from fastapi import HTTPException
import gemini_gateway

ModelID = Literal['budget_cash_flow','savings_goal','bill_split','debt_repayment']
ROUTER_PROMPT = Path(__file__).with_name('routing_prompt.txt').read_text()


class RoutingDecision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    model: Literal['budget_cash_flow','savings_goal','bill_split','debt_repayment','gap','ambiguous','multiple']
    models: list[ModelID] = Field(default_factory=list)
    clarification: str | None = None
    transition: Literal['continuation','new'] | None = None

    @model_validator(mode='before')
    @classmethod
    def empty_optional_models(cls, value):
        if isinstance(value,dict) and value.get('models',[]) is None:
            value={**value,'models':[]}
        return value

    @model_validator(mode='after')
    def coherent(self):
        if self.model=='multiple':
            if len(set(self.models))!=len(self.models) or len(self.models)<2:raise ValueError('Multiple requires distinct models')
        elif self.models:raise ValueError('Only multiple can include model list')
        if self.model=='ambiguous' and not (self.clarification or '').strip():raise ValueError('Ambiguous routing needs an intent question')
        if self.model!='ambiguous' and self.clarification is not None:raise ValueError('Unexpected clarification')
        return self


def route(question, history=None):
    result=gemini_gateway.call_json(ROUTER_PROMPT,json.dumps({'user_question':question,'conversation':history or []}),
                                   stage='model_routing',response_schema=RoutingDecision.model_json_schema())
    try:return RoutingDecision.model_validate(result)
    except ValueError:raise HTTPException(502,'The model selection response was invalid. Please retry.') from None


TRANSITION_RULES = """
You are evaluating a follow-up in an existing financial conversation.
Keep the same financial model for corrections/clarifications of the active question:
return transition=continuation and that same model. A genuinely new question gets
transition=new and its own appropriate model, even if the new question uses the
same model family. Explicit new-question wording is a strong signal; context and
financial intent matter more than keywords. If the transition or intent is unclear,
return model=ambiguous with one question about continuation versus a new question.
For this follow-up response also include transition, overriding the initial example's
model-only envelope. Example: {"model":"bill_split","transition":"new"}.
Omit models unless model=multiple. For ambiguous use transition=null.
Do not extract factors, calculate, or decide execution steps. Python controls them.
"""


def route_followup(message,*,current_model,current_question,history):
    schema=RoutingDecision.model_json_schema()
    schema['required']=list(dict.fromkeys(schema.get('required',[])+['transition']))
    raw=gemini_gateway.call_json(ROUTER_PROMPT+TRANSITION_RULES,
        json.dumps({'followup':message,'active_model':current_model,'active_question':current_question,'conversation':history}),
        stage='model_routing',response_schema=schema)
    try:
        decision=RoutingDecision.model_validate(raw)
        if decision.model in ('gap','ambiguous','multiple'):return decision
        if decision.transition is None or decision.transition=='continuation' and decision.model!=current_model:
            return RoutingDecision(model='ambiguous',clarification='Are you updating the current question or starting a new financial question?')
        return decision
    except ValueError:raise HTTPException(502,'The intent transition could not be interpreted. Please retry.') from None
