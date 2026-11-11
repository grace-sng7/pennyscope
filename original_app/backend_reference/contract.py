"""Pydantic models = the machine-readable version of BACKEND_CONTRACT.md. Do not rename fields."""
from __future__ import annotations
from typing import Any, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, model_validator

Value = Union[float, int, str, None]


class ModelFactor(BaseModel):
    variable: str
    value: Value = None  # structured factors retain the existing JSON-string convention
    unit: Optional[str] = None
    role: Literal['known', 'derived', 'missing']
    source: Literal['stated', 'inferred', 'missing']
    source_detail: str
    relevant: bool = True

    @model_validator(mode='after')
    def consistent_role(self):
        if (self.value is None) != (self.role == 'missing') or (self.value is None) != (self.source == 'missing'):
            raise ValueError('Factor role, source and value disagree')
        return self


def validate_factor_context(model, target, factors):
    if model is not None and model not in ('savings_goal','budget_cash_flow','bill_split','bill_custom','bill_settlement','debt_repayment'):
        raise ValueError('Unknown financial model')
    if factors is not None:
        parsed = [ModelFactor.model_validate(f) for f in factors]
        names = [f.variable for f in parsed]
        if len(names) != len(set(names)) or target is not None and (target not in names or not next(f for f in parsed if f.variable == target).relevant):
            raise ValueError('Duplicate factors or missing target')


# ---------- /extract and /correct (Grace) ----------
class ExtractRequest(BaseModel):
    user_message: str
    reference_date: str      # "YYYY-MM-DD", the user's "today"
    timezone: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    financial_profile: dict[str, Any] = Field(default_factory=dict)


class Assumption(BaseModel):
    model_config = ConfigDict(extra="allow")
    variable: str
    value: Value = None
    unit: Optional[str] = None
    source: Literal["stated", "inferred", "missing"]
    source_detail: str


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="allow")
    target_variable: str
    question: str
    why_it_matters: str


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")   # new top-level fields (e.g. question_type) are passed through
    @model_validator(mode="after")
    def validate_facts(self):
        extra = self.model_extra or {}
        validate_factor_context(extra.get('model'), extra.get('target_variable'), extra.get('factors'))
        names = [a.variable for a in self.assumptions]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate variables")
        if any((a.value is None) != (a.source == "missing") for a in self.assumptions):
            raise ValueError("Missing values and source labels must agree")
        by_name = {a.variable: a for a in self.assumptions}
        if extra.get('model') == 'savings_goal':
            for name in ('goal_amount','target_amount'):
                a = by_name.get(name)
                if a and a.value is not None and a.unit and '/' in a.unit:
                    raise ValueError('A recurring rate is not a one-time savings target; review model selection')
        for factor in extra.get('factors') or []:
            f = ModelFactor.model_validate(factor)
            if f.role == 'known':
                a = by_name.get(f.variable)
                if a is None or a.value != f.value or a.source != f.source or a.unit != f.unit:
                    raise ValueError('Known factor must match its extracted evidence')
        return self

    assumptions: list[Assumption]
    clarification_questions: list[ClarificationQuestion]
    goal_summary: str
    confidence_note: str


class CorrectRequest(ExtractRequest):
    previous_extraction: ExtractionResponse
    user_correction: str


# ---------- /calculate (calculation teammate) ----------
class WireAssumption(BaseModel):
    variable: str
    value: Value = None
    unit: Optional[str] = None
    source: Literal["stated", "inferred", "missing"]
    source_detail: str
    edited_by_user: bool = False


class FreeAnswer(BaseModel):
    target_variable: str
    question: str
    answer: str


class CalculateRequest(BaseModel):
    original_question: str
    assumptions: list[WireAssumption]
    extra_inputs: dict[str, Union[float, int, str]] = Field(default_factory=dict)
    answers: list[FreeAnswer] = Field(default_factory=list)
    parameters: dict[str, float] = Field(default_factory=dict)
    extraction_meta: dict[str, Any] = Field(default_factory=dict)


class MissingInput(BaseModel):
    variable: str
    label: Optional[str] = None
    unit: Optional[str] = None
    help: Optional[str] = None
    input_type: Optional[Literal["number", "text", "date"]] = None


class Parameter(BaseModel):
    key: str                      # letters, digits, _ or - only
    label: str
    value: float
    unit: Optional[str] = None    # "$" shows a currency symbol
    min: Optional[float] = None
    max: Optional[float] = None   # give BOTH min and max to get a slider
    step: Optional[float] = None


class Answer(BaseModel):
    headline: str                 # may contain {parameter_key} placeholders
    detail: Optional[str] = None


class SystemAssumptionOut(BaseModel):
    id: Optional[str] = None
    text: str
    parameter_key: Optional[str] = None
    review_label: Optional[str] = None


class LabelValue(BaseModel):
    label: str
    value: str


class LabelText(BaseModel):
    label: str
    text: str


class CalculateResponse(BaseModel):
    model: Optional[str] = None
    target_variable: Optional[str] = None
    factors: Optional[list[ModelFactor]] = None

    @model_validator(mode='after')
    def factor_context(self):
        validate_factor_context(self.model, self.target_variable, self.factors)
        return self

    status: Literal["ready", "conditional", "needs_input", "unsupported"]
    message: Optional[str] = None            # REQUIRED for needs_input / unsupported
    answer: Optional[Answer] = None          # REQUIRED for ready / conditional
    missing_inputs: list[MissingInput] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    metrics: list[LabelValue] = Field(default_factory=list)
    explanations: list[LabelText] = Field(default_factory=list)
    assumptions: list[SystemAssumptionOut] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
