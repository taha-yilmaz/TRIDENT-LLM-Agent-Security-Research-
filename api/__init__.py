"""
api — FastAPI routers for TRIDENT.
"""
from api.scenarios import router as scenarios_router
from api.evaluator  import router as evaluator_router
from api.results    import router as results_router

__all__ = ["scenarios_router", "evaluator_router", "results_router"]
