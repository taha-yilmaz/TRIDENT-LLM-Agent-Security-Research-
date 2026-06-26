"""
test_crew.py
=============
Quick smoke-test for Stage 3.

Usage
-----
    python test_crew.py [s0|s1|s2|s3] [--model groq|ollama|openai]

Defaults to s1 if no scenario is given. Optional --model overrides MODEL_PROVIDER.

What it does
------------
1. Creates a temporary legitimate candidate file.
2. For S1 / S2: injects a malicious payload to produce a poisoned file.
3. Builds the appropriate CrewAI scenario and runs the crew.
4. Prints the raw crew output to stdout.

This script intentionally does NOT call the evaluator (Stage 4) — it is
purely a connectivity / agent-communication test.
"""

import argparse
import sys
from pathlib import Path

from crewai import Crew, Process

from agent_core.tasks import build_s0_task, build_s1_task, build_s2_tasks, build_s3_task
from utils.groq_backoff import run_with_groq_rate_limit_retry
from utils.payload_injector import inject_payload, S1_PAYLOAD, S2_PAYLOAD
from utils.action_simulator import simulator as action_simulator

S0_KNOWLEDGE_BASE = "sample_docs/poisoned_knowledge_base.txt"

# ---------------------------------------------------------------------------
# Sample legitimate document
# ---------------------------------------------------------------------------
LEGITIMATE_RESUME = """\
Candidate: Bob Martinez
Position: Backend Engineer
Skills: Python, Django, PostgreSQL, Redis, Docker
Experience: 3 years in backend development
Education: B.Sc. Computer Engineering — Istanbul Technical University
Recommendation: Good hire. Solid fundamentals, eager to grow.
"""


def run_scenario(scenario_id: str, provider: str | None = None) -> str:
    """Build and run the requested scenario; return raw crew output."""

    # ---- Create a temp legitimate resume file ----------------------------
    # We create this locally instead of deep in /var/folders/ to prevent LLM hallucinations
    tmp_dir = Path("sample_docs/tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    clean_path = tmp_dir / "legitimate_test_resume.txt"
    with open(clean_path, "w", encoding="utf-8") as f:
        f.write(LEGITIMATE_RESUME)

    scenario_id = scenario_id.lower().strip()
    action_simulator.clear()  # Reset log before each run

    if provider:
        print(f"[TRIDENT] Model provider override: {provider}")

    if scenario_id == "s0":
        print("\n[TRIDENT] Running Scenario S0 — Agent Network Worm")
        kb_path = S0_KNOWLEDGE_BASE
        print(f"[TRIDENT] Knowledge base (poisoned): {kb_path}")
        tasks, agents = build_s0_task(kb_path, provider=provider)

    elif scenario_id == "s1":
        print("\n[TRIDENT] Running Scenario S1 — The Invisible Manager")
        poisoned_path = inject_payload(clean_path, S1_PAYLOAD)
        print(f"[TRIDENT] Poisoned file: {poisoned_path}")
        print(f"[TRIDENT] Payload: {S1_PAYLOAD}\n")
        tasks, agents = build_s1_task(str(poisoned_path), provider=provider)

    elif scenario_id == "s2":
        print("\n[TRIDENT] Running Scenario S2 — Cross-Agent Manipulation")
        poisoned_path = inject_payload(clean_path, S2_PAYLOAD)
        print(f"[TRIDENT] Poisoned file: {poisoned_path}")
        print(f"[TRIDENT] Payload: {S2_PAYLOAD}\n")
        tasks, agents = build_s2_tasks(str(poisoned_path), provider=provider)

    elif scenario_id == "s3":
        print("\n[TRIDENT] Running Scenario S3 — The Time Bomb")
        # S3 uses the clean file; the trigger is in the task description
        tasks, agents = build_s3_task(str(clean_path), provider=provider)

    else:
        raise ValueError(f"Unknown scenario: '{scenario_id}'. Use s0, s1, s2, or s3.")

    # ---- Assemble and kick off the crew ----------------------------------
    crew = Crew(
        agents=agents,
        tasks=tasks,
        process=Process.sequential,
        verbose=True,
    )

    result = run_with_groq_rate_limit_retry(
        lambda: crew.kickoff(),
        what="Crew kickoff",
    )
    return str(result)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TRIDENT CrewAI scenario smoke test")
    parser.add_argument(
        "scenario",
        nargs="?",
        default="s1",
        help="Scenario id: s0, s1, s2, or s3 (default: s1)",
    )
    parser.add_argument(
        "--model",
        dest="provider",
        default=None,
        metavar="PROVIDER",
        help="Override MODEL_PROVIDER: groq, ollama, or openai",
    )
    args = parser.parse_args()

    try:
        output = run_scenario(args.scenario, provider=args.provider)
        print("\n" + "=" * 60)
        print("CREW OUTPUT")
        print("=" * 60)
        print(output)
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        sys.exit(1)
