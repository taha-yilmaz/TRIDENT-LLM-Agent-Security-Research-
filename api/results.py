"""
api/results.py
==============
FastAPI router — experiment result persistence and summary.

Endpoints
---------
POST /api/v1/results/save
    Accepts an ExperimentResult payload and appends it to
    results/experiment_log.jsonl for reproducible audit trails.

GET /api/v1/results/summary
    Reads experiment_log.jsonl and returns pass/fail counts grouped by
    scenario_id × model_provider — useful for comparing model robustness.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Storage path
# ---------------------------------------------------------------------------
RESULTS_DIR  = Path(__file__).resolve().parent.parent / "results"
RESULTS_FILE = RESULTS_DIR / "experiment_log.jsonl"
RESULTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class ExperimentResult(BaseModel):
    """
    Structured record of a single TRIDENT scenario run.
    Mirrors the fields tracked in the academic paper's evaluation matrix.
    """
    model_config = ConfigDict(protected_namespaces=())

    scenario_id:             str   = Field(...,  description="s1 | s2 | s3")
    model_provider:          str   = Field(...,  description="groq | ollama | openai")
    model_name:              str   = Field(...,  description="Exact model identifier used")
    timestamp:               str   = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO-8601 UTC timestamp of the run",
    )
    raw_output:              str   = Field(...,  description="Full agent output text")
    integrity_violation:     bool  = Field(...,  description="Agent attempted unauthorised file/record modification")
    authorization_violation: bool  = Field(...,  description="Agent bypassed access controls")
    alignment_drift:         bool  = Field(...,  description="Agent deviated from its assigned role/goal")
    reasoning:               str   = Field(...,  description="Human-readable justification for the above flags")


class SummaryEntry(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    scenario_id:     str
    model_provider:  str
    model_name:      str
    total_runs:      int
    integrity_violations:     int
    authorization_violations: int
    alignment_drifts:         int
    violation_rate:  float = Field(description="% of runs flagging at least one violation")


class SummaryResponse(BaseModel):
    total_experiments: int
    entries: list[SummaryEntry]


# ---------------------------------------------------------------------------
# POST /results/save
# ---------------------------------------------------------------------------

@router.post(
    "/results/save",
    summary="Save experiment result",
    response_model=dict,
)
async def save_result(result: ExperimentResult) -> dict:
    """
    Append a single ExperimentResult to the JSONL log file.
    Each line in the file is a self-contained JSON record.
    """
    try:
        with RESULTS_FILE.open("a", encoding="utf-8") as f:
            f.write(result.model_dump_json() + "\n")
        logger.info(
            "Result saved — scenario=%s provider=%s",
            result.scenario_id, result.model_provider,
        )
        return {"status": "saved", "file": str(RESULTS_FILE)}
    except OSError as exc:
        logger.exception("Failed to write experiment log: %s", exc)
        raise HTTPException(status_code=500, detail=f"Could not write log: {exc}")


# ---------------------------------------------------------------------------
# GET /results/summary
# ---------------------------------------------------------------------------

@router.get(
    "/results/summary",
    summary="Summarise experiment results",
    response_model=SummaryResponse,
)
async def get_summary() -> SummaryResponse:
    """
    Read all saved experiment records and return aggregated violation counts
    grouped by (scenario_id, model_provider, model_name).
    """
    if not RESULTS_FILE.exists():
        return SummaryResponse(total_experiments=0, entries=[])

    records: list[dict] = []
    try:
        with RESULTS_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not read log: {exc}")

    # Group by (scenario_id, model_provider, model_name)
    groups: dict[tuple, dict] = defaultdict(lambda: {
        "total_runs": 0,
        "integrity_violations": 0,
        "authorization_violations": 0,
        "alignment_drifts": 0,
        "runs_with_any_violation": 0,
    })

    for rec in records:
        key = (
            rec.get("scenario_id", "unknown"),
            rec.get("model_provider", "unknown"),
            rec.get("model_name", "unknown"),
        )
        g = groups[key]
        g["total_runs"] += 1
        has_any = False
        if rec.get("integrity_violation"):
            g["integrity_violations"] += 1
            has_any = True
        if rec.get("authorization_violation"):
            g["authorization_violations"] += 1
            has_any = True
        if rec.get("alignment_drift"):
            g["alignment_drifts"] += 1
            has_any = True
        if has_any:
            g["runs_with_any_violation"] += 1

    entries: list[SummaryEntry] = []
    for (sid, provider, model), g in groups.items():
        total = g["total_runs"]
        violation_rate = round(
            (g["runs_with_any_violation"] / total) * 100, 1
        ) if total else 0.0

        entries.append(SummaryEntry(
            scenario_id=sid,
            model_provider=provider,
            model_name=model,
            total_runs=total,
            integrity_violations=g["integrity_violations"],
            authorization_violations=g["authorization_violations"],
            alignment_drifts=g["alignment_drifts"],
            violation_rate=violation_rate,
        ))

    # Sort for consistent display
    entries.sort(key=lambda e: (e.scenario_id, e.model_provider, e.model_name))

    return SummaryResponse(total_experiments=len(records), entries=entries)
