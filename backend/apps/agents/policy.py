"""Severity policy: what may be blocking, decided here rather than by each agent.

Applied to the raw findings before synthesis merges anything, so one agent's
over-confident "blocking" can no longer promote a group it was merged into. On the
testbed runs 73% of findings were blocking and test coverage alone produced 27 of
38 of them; a reviewer stops reading a review where everything is urgent.

The rules, all deterministic:

1. Scope. An agent reports in its own domain. A test-coverage finding that claims a
   security defect ("could expose SQL injection", on the line that fixes it) is out
   of its depth and dropped, and so is a security-agent finding that is not about
   security. Test coverage's findings are about tests whatever category it chose.
2. Per-agent ceiling. Test coverage is at most a nit: a missing test is worth
   saying, not worth blocking a merge on. Of the tool findings, three kinds may
   block: bandit's own medium/high severity rating, a syntax error (the file does
   not parse), and eval() / new Function() in JS. Every other lint rule is a nit;
   innerHTML-style sinks block only by merging with a Security finding on the line.
3. Evidence. Blocking needs the defect quoted from a line this PR added: evidence
   that matched an added line, or a linter's exact line. A finding on existing code,
   on no line at all, or placed only by the model's number or a snap, is a nit.
4. Certainty. "May", "could", "potentially", "if ... untrusted": a finding that is
   not sure the defect exists is a nit. Model findings only - a tool's wording
   ("Possible SQL injection vector") is its standard phrasing, not doubt.

Every downgrade records why on the finding; every drop is returned with its reason.
"""

import re
from dataclasses import replace

from apps.agents.static_analysis import is_syntax_code
from apps.agents.types import Category, Placement, Severity

# Rule 2: the most an agent's finding can be.
MAX_SEVERITY = {"test_coverage": Severity.NIT}

# Tool rules that may block besides bandit and syntax errors: running a string as
# code is dangerous wherever it appears. innerHTML-style sinks are deliberately not
# here - they block only when the Security agent independently flags the line.
BLOCKING_TOOL_RULES = frozenset({"pattern-scan js-eval", "pattern-scan js-new-function"})

# Rule 1: the categories an agent may report in. Agents not listed are unrestricted.
OWN_CATEGORIES = {"security": {Category.SECURITY}}

_SECURITY_TERMS = (
    r"(?:sql |command |code |template )?injection|xss|cross[- ]site scripting|"
    r"path traversal|ssrf|csrf|remote code execution|"
    r"(?:secret|credential|api key|password|token)s? (?:leak|exposure)|"
    r"unauthori[sz]ed access|privilege escalation"
)
_CLAIM_VERBS = (
    r"expos\w*|allow\w*|enabl\w*|lead\w* to|caus\w*|result\w* in|introduc\w*|"
    r"open\w* (?:up|the door)|vulnerab\w*|exploit\w*|susceptible|unsafe|insecure"
)
# A claim that the code HAS a security defect: a claim verb near a security term
# ("could expose SQL injection", "SQL injection vulnerability"). Merely naming the
# term is not a claim - "untested for SQL injection handling" is a coverage finding.
SECURITY_CLAIM = re.compile(
    rf"\b(?:{_CLAIM_VERBS})\b[^.;]{{0,80}}?\b(?:{_SECURITY_TERMS})\b"
    rf"|\b(?:{_SECURITY_TERMS})\b[^.;]{{0,40}}?\b(?:vulnerab\w*|risk|exploit\w*|attack\w*)",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(?:not|no longer|never)\b\s*$|n't\s*$", re.IGNORECASE)


def claims_security_defect(message):
    """Does the message assert a security defect (rather than mention a topic)?"""
    for match in SECURITY_CLAIM.finditer(message):
        if not _NEGATION.search(message[max(0, match.start() - 20) : match.start()]):
            return True
    return False


SPECULATIVE = re.compile(
    r"\b(?:may|might|could|potentially|possibly|perhaps|presumably)\b"
    r"|\bif\b[^.;]*\b(?:untrusted|user[- ](?:controlled|supplied|provided)|"
    r"attacker[- ]controlled|malicious|tainted)\b",
    re.IGNORECASE,
)


def apply(findings):
    """`(kept, dropped)`: findings with policy severity, and `(finding, reason)` drops."""
    kept, dropped = [], []
    for finding in findings:
        reason = out_of_scope(finding)
        if reason:
            dropped.append((finding, reason))
            continue
        kept.append(cap(_own_category(finding)))
    return kept, dropped


def out_of_scope(finding):
    """Why this agent should not have reported this finding, or ""."""
    if finding.agent == "test_coverage" and claims_security_defect(finding.message):
        return "out of scope: test coverage making a security claim"
    allowed = OWN_CATEGORIES.get(finding.agent)
    if allowed is not None and finding.category not in allowed:
        return f"out of scope: {finding.agent} reporting {finding.category}"
    return ""


def _own_category(finding):
    if finding.agent == "test_coverage" and finding.category != Category.TESTING:
        return replace(finding, category=Category.TESTING)
    return finding


def blocking_denied(finding):
    """Why this finding may not be blocking, or "" if it may."""
    ceiling = MAX_SEVERITY.get(finding.agent)
    if ceiling == Severity.NIT:
        return f"{finding.agent.replace('_', ' ')} is never blocking"

    if finding.agent == "static_analysis":
        if finding.rule.startswith("bandit ") or finding.rule in BLOCKING_TOOL_RULES:
            return ""  # on the exact added line, which the tool named
        tool, _, code = finding.rule.partition(" ")
        if tool == "ruff" and is_syntax_code(code):
            return ""  # the file does not parse
        return "lint rule"

    if finding.placement == Placement.EXISTING:
        return "about code this PR did not change"
    if finding.placement == Placement.GENERAL:
        return "not anchored to a line this PR added"
    if finding.anchored_by != "evidence":
        return "no evidence quoted from an added line"
    if SPECULATIVE.search(finding.message):
        return "speculative wording"
    return ""


def cap(finding):
    if finding.severity != Severity.BLOCKING:
        return finding
    reason = blocking_denied(finding)
    if not reason:
        return finding
    return replace(finding, severity=Severity.NIT, downgraded=reason)
