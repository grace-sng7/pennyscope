"""Run:  uvicorn main:app --reload --port 8000      (from this folder)
Interactive docs & manual testing:  http://localhost:8000/docs
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import extraction_service
import orchestration
from contract import CalculateRequest, CalculateResponse, CorrectRequest, ExtractionResponse, ExtractRequest

app = FastAPI(title="Pennyscope backend")
# The frontend talks to us through its own server (no CORS needed), but this makes /docs and direct tests easy.
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/extract", response_model=ExtractionResponse)
def extract(req: ExtractRequest):
    return extraction_service.extract(req.user_message, req.reference_date, req.timezone, history=req.history, financial_profile=req.financial_profile)


@app.post("/correct", response_model=ExtractionResponse)
def correct(req: CorrectRequest):
    return extraction_service.correct(req.user_message, req.reference_date, req.timezone, req.previous_extraction.model_dump(), req.user_correction, history=req.history or None, financial_profile=req.financial_profile)


@app.post("/calculate", response_model=CalculateResponse)
def calculate(req: CalculateRequest):
    route = req.extraction_meta.get('routing', {}).get('model')
    if route == 'gap':
        return {'status':'unsupported','message':'This question does not match one of the four existing financial models.'}
    if route in ('ambiguous','multiple'):
        routing = req.extraction_meta['routing']
        return {'status':'needs_input','message':'Clarify the financial intent before calculation.',
                'missing_inputs':[{'variable':'model_selection','label':routing.get('clarification') or 'Which part of your question should we address first?', 'input_type':'text'}]}
    # To add a new question type: write another module with the same dict-in/dict-out shape,
    # and choose between models here (e.g. by req.extraction_meta.get("question_type")).
    return orchestration.calculate(req.model_dump())
