"""Step 8 absolute rubric (ResearchAgent-derived 10 Problem/Method metrics). Sidecar to ``step8_hypothesis.json``."""

from .metrics import METRICS, MetricDef, metric_by_id
from .runner import run_step8_rubric

__all__ = ["METRICS", "MetricDef", "metric_by_id", "run_step8_rubric"]
