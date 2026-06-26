"""
evaluator — LLM-powered security log analyzer for TRIDENT (Stage 4).
"""
from evaluator.analyzer import SecurityEvaluationResult, evaluate_agent_logs

__all__ = ["SecurityEvaluationResult", "evaluate_agent_logs"]
