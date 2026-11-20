"""Run:  uvicorn main:app --reload --port 8000      (from this folder)
Interactive docs & manual testing:  http://localhost:8000/docs
"""
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import extraction_service
import orchestration
import chat_fallback
import question_approach
from contract import CalculateRequest, CalculateResponse, CorrectRequest, ExtractionResponse, ExtractRequest, ChatFallbackRequest, PlainChat

LOGGER=logging.getLogger(__name__)

app = FastAPI(title="Pennyscope backend")
# The frontend talks to us through its own server (no CORS needed), but this makes /docs and direct tests easy.
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/extract", response_model=ExtractionResponse)
def extract(req: ExtractRequest):
    try:
        result=extraction_service.extract(req.user_message, req.reference_date, req.timezone, history=req.history, financial_profile=req.financial_profile)
        return ExtractionResponse.model_validate(result).model_dump(exclude_unset=True)
    except Exception as exc:
        facts=getattr(exc,'confirmed_factors',[])
        invalid=getattr(exc,'invalid_factor_ids',[])
        LOGGER.warning('extraction_recovery validation=%s invalid_factors=%s confirmed_count=%d',getattr(exc,'validation_stage',type(exc).__name__),','.join(invalid),len(facts))
        result=chat_fallback.extraction_response(req.user_message,facts,model=getattr(exc,'selected_model',None),target_variable=getattr(exc,'target_variable',None),reference_date=req.reference_date,timezone=req.timezone)
        result['processing_issues']=[dict(stage='factor_extraction',code='structured_recovery',invalid_factor_ids=invalid)]
        return result


@app.post("/correct", response_model=ExtractionResponse)
def correct(req: CorrectRequest):
    try:
        result=extraction_service.correct(req.user_message, req.reference_date, req.timezone, req.previous_extraction.model_dump(), req.user_correction, history=req.history or None, financial_profile=req.financial_profile)
        return ExtractionResponse.model_validate(result).model_dump(exclude_unset=True)
    except Exception as exc:
        facts=[a.model_dump() for a in req.previous_extraction.assumptions]+getattr(exc,'confirmed_factors',[])
        return chat_fallback.extraction_response(req.user_message,facts,correction=req.user_correction,
            model=getattr(exc,'selected_model',None) or req.previous_extraction.model_extra.get('model'),
            target_variable=getattr(exc,'target_variable',None) or req.previous_extraction.model_extra.get('target_variable'),reference_date=req.reference_date,timezone=req.timezone)


@app.post("/calculate", response_model=CalculateResponse)
def calculate(req: CalculateRequest):
    route = req.extraction_meta.get('routing', {}).get('model')
    answered = any(a.target_variable in ('model_selection','target_selection') for a in req.answers) or bool(set(req.extra_inputs) & {'model_selection','target_selection'})
    if route in ('ambiguous','multiple') and not answered:
        routing = req.extraction_meta['routing']
        return {'status':'needs_input','message':'Clarify the financial intent before calculation.',
                'missing_inputs':[{'variable':'model_selection','label':routing.get('clarification') or 'Which part of your question should we address first?', 'input_type':'text'}]}
    try:
        if route=='gap' and not answered:
            result=question_approach.calculate(req.model_dump())
        else:
            result=orchestration.calculate(req.model_dump())
            if result.get('status')=='unsupported':
                result=question_approach.calculate(req.model_dump())
        return CalculateResponse.model_validate(result).model_dump(exclude_unset=True)
    except Exception:
        # Provider/presentation failures cannot bypass known missing-input
        # checks and turn an incomplete question into a plain-language verdict.
        try:
            import calculation_handoff
            facts={a.variable:a.model_dump() for a in req.assumptions}
            _,clarification=(None,None) if chat_fallback.from_main(locals().get('result')) else calculation_handoff.resolve(req.model_dump(),facts)
            if clarification and clarification.get('status')=='needs_input':return clarification
        except (ValueError,TypeError,KeyError):pass
        reply=chat_fallback.respond(req.original_question,[a.model_dump() for a in req.assumptions],existing_main=locals().get('result'))
        return {'status':'conditional' if reply['kind']=='answer' else 'needs_input','answer':{'headline':reply['text']} if reply['kind']=='answer' else None,'message':reply['text'] if reply['kind']!='answer' else None,'chat_fallback':reply}


@app.post('/chat-fallback',response_model=PlainChat)
def plain_chat(req:ChatFallbackRequest):
    return chat_fallback.respond(req.user_message,[a.model_dump() for a in req.confirmed_facts],
                                 correction=req.user_correction,existing_main=req.existing_main)
