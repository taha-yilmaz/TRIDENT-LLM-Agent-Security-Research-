"""
TRIDENT — Main FastAPI Application Entry Point
================================================
Stages wired here:
  Stage 1  →  GET  /health
  Stage 5  →  POST /api/v1/scenarios/run
              POST /api/v1/evaluator/analyze
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.scenarios import router as scenarios_router
from api.evaluator  import router as evaluator_router
from api.results    import router as results_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("trident")


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown hooks)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("TRIDENT API starting up…")
    yield
    logger.info("TRIDENT API shutting down.")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="TRIDENT — LLM Agent Security Research API",
    description=(
        "Academic backend for red-teaming LLM-based AI Agents across "
        "four scenarios (S0–S3):\n\n"
        "- **S0** Agent Network (RAG) — Morris-II style propagation\n"
        "- **S1** Input Layer — Prompt Injection via poisoned documents\n"
        "- **S2** Process Layer — Cross-Agent Manipulation\n"
        "- **S3** Output Layer — Time-Bomb / Trigger-Word Exploits\n\n"
        "All scenarios are simulated in a sandboxed environment."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(scenarios_router, prefix="/api/v1", tags=["Scenarios"])
app.include_router(evaluator_router, prefix="/api/v1", tags=["Evaluator"])
app.include_router(results_router,   prefix="/api/v1", tags=["Results"])


# ---------------------------------------------------------------------------
# Stage 1 — Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["System"], summary="Liveness probe")
async def health_check():
    """Returns API status. Use this to confirm the server is running."""
    return {"status": "TRIDENT API is running", "version": "1.0.0"}


# ---------------------------------------------------------------------------
# Root redirect → docs
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def root():
    return JSONResponse(
        {"message": "TRIDENT API is live. Visit /docs for the interactive interface."}
    )
