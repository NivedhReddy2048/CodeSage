"""The review pipeline, as a plain Python package.

Imports nothing from Django: configuration arrives as a `ReviewConfig` from the
caller, and the `reviews` app owns all persistence and GitHub calls. Phase 5 grows
this into the LangGraph multi-agent pipeline behind the same entry point.
"""

from apps.agents.graph import run_pipeline
from apps.agents.review import run_review
from apps.agents.types import (
    AgentRun,
    Category,
    Finding,
    LLMCall,
    RepoContext,
    RetrievedChunk,
    ReviewConfig,
    ReviewResult,
    Severity,
)

__all__ = [
    "run_review",
    "run_pipeline",
    "Category",
    "Finding",
    "LLMCall",
    "AgentRun",
    "RepoContext",
    "RetrievedChunk",
    "ReviewConfig",
    "ReviewResult",
    "Severity",
]
