"""Value types crossing the agents boundary.

Plain dataclasses on purpose. This package must not import Django (the Phase 4
architecture note), so configuration arrives as `ReviewConfig` built by the caller
rather than being read from settings here. That is what keeps the boundary real
instead of aspirational: the package can be tested, and later reused, with no
settings module present.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    BLOCKING = "blocking"
    NIT = "nit"


class Category(StrEnum):
    """Finding categories.

    Fixed rather than free text so Phase 8's evaluation can match a finding against a
    planted bug by category. The six bug types spec §16 names map onto these.
    """

    CORRECTNESS = "correctness"
    SECURITY = "security"
    PERFORMANCE = "performance"
    ERROR_HANDLING = "error-handling"
    CONCURRENCY = "concurrency"
    RESOURCE_LEAK = "resource-leak"
    TESTING = "testing"
    STYLE = "style"
    OTHER = "other"


class Placement(StrEnum):
    """Where a finding is shown, decided by `anchoring` rather than by the model."""

    INLINE = "inline"  # on a line the PR added: summary and an inline comment
    EXISTING = "existing"  # about code the PR did not change: summary only, collapsed
    GENERAL = "general"  # no line it can honestly be pinned to: summary only


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    severity: Severity
    category: Category
    message: str
    agent: str = "review"
    # Grounding only: the verified `path:start-end` of the existing code this
    # finding rests on. Stored on ReviewFinding.citation.
    cited: str = ""
    # The changed line(s) the agent quotes as the defect, verbatim.
    evidence: str = ""
    placement: Placement = Placement.INLINE
    # How `line` was chosen: "evidence" (the quote was found on that line), "cited"
    # (the model's own number, which was an added line), "snapped" (moved onto a
    # nearby added line), "tool" (a linter's exact line), or "" for general ones.
    anchored_by: str = ""
    # Static analysis only: the tool and its rule id, e.g. "bandit B608", "ruff F401".
    rule: str = ""
    # Set by the severity policy when it lowered this finding: why.
    downgraded: str = ""

    @property
    def citation(self):
        return self.file, self.line


@dataclass
class LLMCall:
    """Telemetry for one provider call, stored against the Review (spec §14)."""

    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    succeeded: bool = False
    is_fallback: bool = False
    error: str = ""


@dataclass
class DiffFile:
    path: str
    # Line numbers present in the new version of the file, which are the only lines a
    # finding may cite: a comment on a line not in the diff would render detached
    # from the change on GitHub.
    changed_lines: set[int] = field(default_factory=set)
    # The subset of changed_lines the PR added or modified ("+" lines), as opposed to
    # context shown around them. Only these are the author's change.
    added_lines: set[int] = field(default_factory=set)
    text: str = ""
    # True when the diff added the file, which means its hunks are the complete new
    # content. Static analysis needs the distinction: only then is a syntax error in
    # the reconstruction the author's, rather than an artefact of seeing part of a file.
    is_new_file: bool = False


@dataclass
class PreparedDiff:
    """A diff after filtering and truncation, ready to show a model."""

    text: str
    files: list[DiffFile] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    truncated: bool = False
    original_bytes: int = 0
    included_bytes: int = 0

    def allows(self, path, line):
        """May a comment be anchored here? Only on a line the PR added.

        Context lines are shown for reading, not for comments: a comment on one is
        either about code the author did not write or about the wrong line.
        """
        for entry in self.files:
            if entry.path == path:
                return line in entry.added_lines
        return False

    def entry(self, path):
        return next((entry for entry in self.files if entry.path == path), None)


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk handed to the grounding agent.

    Plain data, built by the caller from CodeChunk rows, so the agents package stays
    free of the ORM.
    """

    file_path: str
    symbol: str
    line_start: int
    line_end: int
    content: str
    score: float = 0.0

    def covers(self, file_path, line):
        """Whether a cited line falls inside this chunk."""
        return self.file_path == file_path and self.line_start <= line <= self.line_end


@dataclass
class RepoContext:
    """What the reviewer knows about the change, beyond the diff itself."""

    full_name: str = ""
    pr_number: int = 0
    pr_title: str = ""
    base_branch: str = ""
    head_sha: str = ""


@dataclass
class AgentRun:
    """Telemetry for one agent in the pipeline (spec section 14)."""

    name: str
    # The model that actually served the call. Telemetry and cost are based on this,
    # so after a failover it names the fallback model, never the one asked for.
    model: str = ""
    provider: str = ""
    # The model the agent asked for. Differs from `model` only after a failover.
    requested_model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    succeeded: bool = False
    used_fallback: bool = False
    # Set when the agent was skipped rather than run, e.g. the token budget ran out.
    skipped_reason: str = ""
    findings_count: int = 0
    error: str = ""
    # Free-text detail for agents that are not a model call, e.g. which linters
    # static analysis actually ran and which it could not.
    detail: str = ""


@dataclass
class ReviewConfig:
    """Everything the package needs, supplied by the caller."""

    groq_api_key: str = ""
    gemini_api_key: str = ""
    # Model tiering against the shared 8000 TPM ceiling: the big model only where
    # judgement matters most, the cheap one for classification and narrow passes.
    primary_model: str = "openai/gpt-oss-120b"
    cheap_model: str = "openai/gpt-oss-20b"
    fallback_model: str = "gemini-flash-lite-latest"

    # Total tokens one review may spend across every agent. Groq reports 8000 TPM
    # and the bucket looks shared across models, so this leaves headroom rather
    # than racing the limit and 429-ing partway through.
    token_budget: int = 6500
    request_timeout: int = 90
    max_retries: int = 3
    backoff_seconds: float = 2.0
    max_diff_bytes: int = 24000
    max_findings: int = 25
    breaker_failure_threshold: int = 3
    breaker_reset_seconds: float = 300.0
    # Static analysis lints a modified file's full content when the caller can fetch
    # it; anything larger than this is linted from the diff's hunks instead.
    max_source_bytes: int = 256 * 1024


@dataclass
class ReviewResult:
    """The package's only output."""

    findings: list[Finding] = field(default_factory=list)
    calls: list[LLMCall] = field(default_factory=list)
    duration_ms: int = 0
    succeeded: bool = False
    # Set when no provider produced usable output. The caller surfaces this in the
    # PR comment instead of a traceback.
    failure_reason: str = ""
    skipped_files: list[str] = field(default_factory=list)
    truncated: bool = False
    model_used: str = ""
    used_fallback: bool = False
    # Per-agent telemetry (spec section 14), and agents the budget forced out.
    agent_runs: list = field(default_factory=list)
    skipped_agents: list = field(default_factory=list)
    # (finding, reason) for raw findings the severity policy removed as out of scope.
    dropped: list = field(default_factory=list)

    @property
    def blocking(self):
        return [f for f in self.findings if f.severity == Severity.BLOCKING]

    @property
    def nits(self):
        return [f for f in self.findings if f.severity == Severity.NIT]
