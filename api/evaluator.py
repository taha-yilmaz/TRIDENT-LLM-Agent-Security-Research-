"""
api/evaluator.py
=================
FastAPI router — POST /api/v1/evaluator/analyze

Accepts raw agent log text and returns a structured SecurityEvaluationResult.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from evaluator.analyzer import SecurityEvaluationResult, evaluate_agent_logs

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class EvaluatorRequest(BaseModel):
    log_text: str = Field(
        ...,
        min_length=10,
        description="Raw agent output / crew log text to analyze.",
        examples=["Agent deleted all candidate records after reading poisoned file."],
    )


class EvaluatorResponse(BaseModel):
    integrity_violation:    bool
    authorization_violation: bool
    alignment_drift:        bool
    reasoning:              str
    status: str = "analyzed"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/evaluator/analyze", response_model=EvaluatorResponse)
async def analyze_logs(request: EvaluatorRequest) -> EvaluatorResponse:
    """
    Analyze raw agent logs for security violations.

    Returns a **SecurityEvaluationResult** indicating whether the agents
    exhibited integrity violations, authorization violations, or alignment
    drift during their run.
    """
    try:
        result: dict = evaluate_agent_logs(request.log_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        logger.exception("Evaluator LLM error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Evaluator LLM error: {exc}")
    except Exception as exc:
        logger.exception("Unexpected evaluator error: %s", exc)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {exc}")

    return EvaluatorResponse(**result)
