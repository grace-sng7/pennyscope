"""Run:  uvicorn main:app --reload --port 8000      (from this folder)
Interactive docs & manual testing:  http://localhost:8000/docs

Decision path (penny_pipeline.py): classify the question into one of the four
Penny Scope models, extract that model's inputs, and calculate with the model's
formulas in Python. Questions that fit no model get a free-thinking answer.
The previous multi-stage pipeline is kept in legacy_main.py for reference.
"""
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import penny_pipeline as pipeline
from contract import (CalculateRequest, CalculateResponse, ChatFallbackRequest, CorrectRequest,
                      ExtractRequest, ExtractionResponse, PlainChat)

LOGGER = logging.getLogger(__name__)

app = FastAPI(title="Pennyscope backend")
# The frontend talks to us through its own server (no CORS needed), but this makes /docs and direct tests easy.
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"ok": True}


def _free_extraction(question, correction=None):
    return ExtractionResponse.model_validate(pipeline._free_response(question, {}, correction)).model_dump(exclude_unset=True)


@app.post("/extract", response_model=ExtractionResponse)
def extract(req: ExtractRequest):
    try:
        result = pipeline.extract(req.user_message, req.reference_date, profile=req.financial_profile)
        return ExtractionResponse.model_validate(result).model_dump(exclude_unset=True)
    except HTTPException:
        raise  # provider outage: the UI offers Retry
    except Exception:
        LOGGER.exception('extract failed; answering with free thinking')
        return _free_extraction(req.user_message)


@app.post("/correct", response_model=ExtractionResponse)
def correct(req: CorrectRequest):
    try:
        result = pipeline.correct(req.user_message, req.reference_date, req.previous_extraction.model_dump(),
                                  req.user_correction, profile=req.financial_profile)
        return ExtractionResponse.model_validate(result).model_dump(exclude_unset=True)
    except HTTPException:
        raise
    except Exception:
        LOGGER.exception('correct failed; answering with free thinking')
        return _free_extraction(req.user_message, correction=req.user_correction)


@app.post("/calculate", response_model=CalculateResponse)
def calculate(req: CalculateRequest):
    result = pipeline.calculate(req.model_dump())
    return CalculateResponse.model_validate(result).model_dump(exclude_unset=True)


@app.post('/chat-fallback', response_model=PlainChat)
def plain_chat(req: ChatFallbackRequest):
    return pipeline.free_think(req.user_message, [a.model_dump() for a in req.confirmed_facts], req.user_correction)
