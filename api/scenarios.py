"""
api/scenarios.py
=================
FastAPI router — scenario execution endpoints.

POST /api/v1/scenarios/run and POST /api/v1/scenarios/batch accept a scenario
ID (s0–s3), target file path, optional auto-poisoning, and model provider,
then run the corresponding CrewAI crew and return outputs (and batch metrics).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from crewai import Crew, Process
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from agent_core.agents import get_model_name
from agent_core.tasks import build_s0_task, build_s1_task, build_s2_tasks, build_s3_task
from evaluator.analyzer import evaluate_agent_logs
from utils.groq_backoff import run_with_groq_rate_limit_retry
from utils.payload_injector import inject_payload, S1_PAYLOAD, S2_PAYLOAD
from utils.action_simulator import simulator as action_simulator

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ScenarioRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    scenario_id: str = Field(
        ...,
        pattern="^(s0|s1|s2|s3)$",
        description="Scenario identifier: 's0', 's1', 's2', or 's3'.",
        examples=["s1"],
    )
    target_file_path: str = Field(
        ...,
        description="Path to the target .txt or .md document on the server.",
        examples=["sample_docs/candidate_alice.txt"],
    )
    auto_poison: bool = Field(
        default=True,
        description=(
            "If True (default), the target file is automatically poisoned "
            "before being passed to the agent (S1 / S2 only). "
            "Set to False to pass the file as-is."
        ),
    )
    model_provider: str = Field(
        default="groq",
        description="LLM provider: 'groq' (default) | 'ollama' | 'openai'.",
        examples=["groq", "ollama", "openai"],
    )


class ScenarioResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    scenario_id: str
    model_provider: str
    model_name: str
    target_file: str
    poisoned_file: str | None = None
    raw_output: str
    action_log: str | None = None
    status: str = "completed"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/scenarios/run", response_model=ScenarioResponse)
async def run_scenario(request: ScenarioRequest) -> ScenarioResponse:
    """
    Trigger a TRIDENT attack scenario.

    - **s0** — Agent Network Worm: worm payload in a knowledge base propagates across agents.
    - **s1** — The Invisible Manager: single HR agent reads a poisoned file.
    - **s2** — Cross-Agent Manipulation: HR agent forwards tainted instructions to System Admin.
    - **s3** — The Time Bomb: trigger token embedded in task description.
    """
    target_path = Path(request.target_file_path)

    if not target_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Target file not found: {request.target_file_path}",
        )

    action_simulator.clear()  # Reset log before each scenario run
    poisoned_path: Path | None = None

    try:
        sid = request.scenario_id.lower()

        provider = request.model_provider

        if sid == "s0":
            kb_path = str(target_path)
            tasks, agents = build_s0_task(kb_path, provider=provider)

        elif sid == "s1":
            if request.auto_poison:
                poisoned_path = inject_payload(target_path, S1_PAYLOAD)
                file_for_agent = str(poisoned_path)
            else:
                file_for_agent = str(target_path)
            tasks, agents = build_s1_task(file_for_agent, provider=provider)

        elif sid == "s2":
            if request.auto_poison:
                poisoned_path = inject_payload(target_path, S2_PAYLOAD)
                file_for_agent = str(poisoned_path)
            else:
                file_for_agent = str(target_path)
            tasks, agents = build_s2_tasks(file_for_agent, provider=provider)

        else:  # s3
            tasks, agents = build_s3_task(str(target_path), provider=provider)

        crew = Crew(
            agents=agents,
            tasks=tasks,
            process=Process.sequential,
            verbose=True,
            max_rpm=10,
        )

        result = run_with_groq_rate_limit_retry(
            lambda: crew.kickoff(),
            what="Crew kickoff",
        )
        raw_output = str(result)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Scenario %s failed: %s", request.scenario_id, exc)
        raise HTTPException(status_code=500, detail=f"Scenario execution failed: {exc}")

    return ScenarioResponse(
        scenario_id=request.scenario_id,
        model_provider=provider,
        model_name=get_model_name(provider),
        target_file=str(target_path),
        poisoned_file=str(poisoned_path) if poisoned_path else None,
        raw_output=raw_output,
        action_log=action_simulator.get_log_text() if action_simulator.action_log else None,
    )


# ---------------------------------------------------------------------------
# Batch run — repeat a scenario N times, auto-evaluate, persist results
# ---------------------------------------------------------------------------

class BatchRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    scenario_id: str = Field(
        ..., pattern="^(s0|s1|s2|s3)$",
        description="Scenario identifier.",
    )
    target_file_path: str = Field(
        ..., description="Path to the target document.",
    )
    auto_poison: bool = Field(default=True)
    model_provider: str = Field(
        default="groq",
        description="LLM provider: 'groq' | 'ollama' | 'openai'.",
    )
    repeat: int = Field(
        default=5, ge=1, le=50,
        description="Number of times to run the scenario (default 5).",
    )


class RunDetail(BaseModel):
    run_index: int
    integrity_violation: bool
    authorization_violation: bool
    alignment_drift: bool
    reasoning: str


class BatchResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    scenario_id: str
    model_provider: str
    model_name: str
    total_runs: int
    integrity_violations: int
    authorization_violations: int
    alignment_drifts: int
    integrity_rate: float = Field(description="% of runs with integrity violation")
    authorization_rate: float = Field(description="% of runs with authorization violation")
    alignment_rate: float = Field(description="% of runs with alignment drift")
    any_violation_rate: float = Field(description="% of runs with at least one violation")
    runs: list[RunDetail]


@router.post(
    "/scenarios/batch",
    response_model=BatchResponse,
    summary="Run a scenario N times and return aggregated metrics",
)
async def run_batch(request: BatchRequest) -> BatchResponse:
    """
    Execute a scenario *repeat* times, automatically evaluate each run,
    persist results to experiment_log.jsonl, and return aggregated
    violation rates (ASR-like metrics for the paper).
    """
    from api.results import RESULTS_FILE

    target_path = Path(request.target_file_path)
    if not target_path.exists():
        raise HTTPException(404, f"Target file not found: {request.target_file_path}")

    provider = request.model_provider
    model_name = get_model_name(provider)
    runs: list[RunDetail] = []

    int_v = auth_v = align_v = any_v = 0

    for i in range(request.repeat):
        action_simulator.clear()
        poisoned_path: Path | None = None

        try:
            sid = request.scenario_id.lower()

            if sid == "s0":
                tasks, agents = build_s0_task(str(target_path), provider=provider)
            elif sid == "s1":
                if request.auto_poison:
                    poisoned_path = inject_payload(target_path, S1_PAYLOAD)
                    file_for_agent = str(poisoned_path)
                else:
                    file_for_agent = str(target_path)
                tasks, agents = build_s1_task(file_for_agent, provider=provider)
            elif sid == "s2":
                if request.auto_poison:
                    poisoned_path = inject_payload(target_path, S2_PAYLOAD)
                    file_for_agent = str(poisoned_path)
                else:
                    file_for_agent = str(target_path)
                tasks, agents = build_s2_tasks(file_for_agent, provider=provider)
            else:
                tasks, agents = build_s3_task(str(target_path), provider=provider)

            crew = Crew(
                agents=agents, tasks=tasks,
                process=Process.sequential, verbose=True, max_rpm=10,
            )
            raw_output = str(
                run_with_groq_rate_limit_retry(
                    lambda: crew.kickoff(),
                    what="Crew kickoff",
                )
            )

            log_for_eval = raw_output
            action_log_text = action_simulator.get_log_text() if action_simulator.action_log else ""
            if action_log_text:
                log_for_eval += "\n\nACTION LOG:\n" + action_log_text

            eval_result = evaluate_agent_logs(log_for_eval)

        except Exception as exc:
            logger.exception("Batch run %d/%d failed: %s", i + 1, request.repeat, exc)
            eval_result = {
                "integrity_violation": False,
                "authorization_violation": False,
                "alignment_drift": False,
                "reasoning": f"Run failed with error: {exc}",
            }
            raw_output = f"[ERROR] {exc}"

        iv = eval_result["integrity_violation"]
        av = eval_result["authorization_violation"]
        ad = eval_result["alignment_drift"]

        int_v += iv
        auth_v += av
        align_v += ad
        if iv or av or ad:
            any_v += 1

        runs.append(RunDetail(
            run_index=i + 1,
            integrity_violation=iv,
            authorization_violation=av,
            alignment_drift=ad,
            reasoning=eval_result["reasoning"],
        ))

        record = {
            "scenario_id": request.scenario_id,
            "model_provider": provider,
            "model_name": model_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "raw_output": raw_output[:2000],
            "integrity_violation": iv,
            "authorization_violation": av,
            "alignment_drift": ad,
            "reasoning": eval_result["reasoning"],
        }
        try:
            with RESULTS_FILE.open("a", encoding="utf-8") as f:
                import json
                f.write(json.dumps(record) + "\n")
        except OSError:
            logger.warning("Could not persist run %d to JSONL.", i + 1)

    n = request.repeat
    return BatchResponse(
        scenario_id=request.scenario_id,
        model_provider=provider,
        model_name=model_name,
        total_runs=n,
        integrity_violations=int_v,
        authorization_violations=auth_v,
        alignment_drifts=align_v,
        integrity_rate=round(int_v / n * 100, 1),
        authorization_rate=round(auth_v / n * 100, 1),
        alignment_rate=round(align_v / n * 100, 1),
        any_violation_rate=round(any_v / n * 100, 1),
        runs=runs,
    )
