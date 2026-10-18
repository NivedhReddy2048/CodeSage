"""The review pipeline, as a plain Python package.

Imports nothing from Django: configuration arrives as a `ReviewConfig` from the
caller, and the `reviews` app owns all persistence and GitHub calls. Phase 5 grows
this into the LangGraph multi-agent pipeline behind the same entry point.
"""

from apps.agents.review import run_review
from apps.agents.types import (
    Category,
    Finding,
    LLMCall,
    RepoContext,
    ReviewConfig,
    ReviewResult,
    Severity,
)

__all__ = [
    "run_review",
    "Category",
    "Finding",
    "LLMCall",
    "RepoContext",
    "ReviewConfig",
    "ReviewResult",
    "Severity",
]
