"""Severity policy: what may be blocking, decided here rather than by each agent.

Applied to the raw findings before synthesis merges anything, so one agent's
over-confident "blocking" can no longer promote a group it was merged into. On the
testbed runs 73% of findings were blocking and test coverage alone produced 27 of
38 of them; a reviewer stops reading a review where everything is urgent.

The rules, all deterministic:

1. Scope. An agent reports in its own domain. A test-coverage or correctness
   finding that claims a security defect ("could expose SQL injection", on the line
   that fixes it) is out of its depth and dropped, and so is a security-agent finding
   that is not about security, or a correctness finding about tests, style or
   performance. Test coverage's findings are about tests whatever category it chose.
   Grounding may not fault a change for being safer than the code it cites
   ("uses a parameterized query while existing code uses f-strings"): existing code
   is precedent only when it is not itself a defect.
2. Per-agent ceiling. Test coverage is at most a nit: a missing test is worth
   saying, not worth blocking a merge on. Of the tool findings, four kinds may
   block: bandit's own medium/high severity rating, a syntax error (the file does
   not parse), an undefined name in a whole file (static analysis leaves it a nit
   where a star import or module __getattr__ could define it), and eval() /
   new Function() in JS. Every other lint rule is a nit; innerHTML-style sinks
   block only by merging with a Security finding on the line.
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

from apps.agents.static_analysis import is_blocking_lint
from apps.agents.types import Category, Placement, Severity

# Rule 2: the most an agent's finding can be.
MAX_SEVERITY = {"test_coverage": Severity.NIT}

# Tool rules that may block besides bandit and syntax errors: running a string as
# code is dangerous wherever it appears. innerHTML-style sinks are deliberately not
# here - they block only when the Security agent independently flags the line.
BLOCKING_TOOL_RULES = frozenset({"pattern-scan js-eval", "pattern-scan js-new-function"})

# Rule 1: the categories an agent may report in. Agents not listed are unrestricted.
# Correctness owns defects in what the code does; security, tests, style and
# performance belong to other agents or to no one.
OWN_CATEGORIES = {
    "security": {Category.SECURITY},
    "correctness": {
        Category.CORRECTNESS,
        Category.ERROR_HANDLING,
        Category.CONCURRENCY,
        Category.RESOURCE_LEAK,
        Category.OTHER,
    },
}

# Rule 1: agents whose security claims are out of their depth.
NO_SECURITY_CLAIMS = {"test_coverage": "test coverage", "correctness": "correctness"}

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


# Rule 1 for grounding. A consistency claim...
_INCONSISTENT = re.compile(
    r"\binconsisten\w*|\bdeviat\w*|\bdiffers? from\b|\bunlike (?:the )?(?:existing|other|rest)\b"
    r"|\b(?:established|existing) (?:pattern|convention|style|approach)\b"
    r"|\bdoes(?:n't| not) follow\b",
    re.IGNORECASE,
)
# ...naming a construct that is unambiguously the safer way, which the quoted added
# line really uses. The direction is read from the code, not the prose: "this does not
# close the connection, unlike existing code which uses a context manager" names the
# same construct and is a real finding, and its added line has no `with`.
#
# Validation is left out on purpose: "inconsistent with the existing
# `is_valid_email`" is a duplication finding, which is grounding's job. The prompt
# states the general rule; this is the backstop, because on testbed-pr5 gpt-oss-20b
# still broke it with the rule in its prompt (issue #122).
_INTERPOLATED = re.compile(r"""\b[fF]["']|\.format\(|["']\s*[%+]|\+\s*["']""")


def _bound_sql(code):
    """Is this line a query with bound parameters, and no string building?"""
    if _INTERPOLATED.search(code):
        return False
    if re.search(r"\.execute(?:many)?\(\s*[^,()]+,", code):
        return True
    return bool(
        re.search(r"\b(?:SELECT|INSERT|UPDATE|DELETE)\b", code, re.IGNORECASE)
        and re.search(r"\?|%s|:\w+|\$\d", code)
    )


_SAFER = (
    (
        # A bound SQL query: a placeholder in the statement, or parameters passed.
        re.compile(
            r"\bparameteri[sz](?:ed|ation)\b|\bprepared statements?\b|\bbound parameters?\b"
            r"|\bplaceholders?\b",
            re.IGNORECASE,
        ),
        _bound_sql,
    ),
    (
        # A resource that is closed.
        re.compile(
            r"\bcontext manager\b|\bwith[- ]statement\b|\bwith block\b"
            r"|\bclos(?:es|ing|ed) (?:the |a |its )?(?:connection|file|cursor|handle|resource)s?\b",
            re.IGNORECASE,
        ),
        lambda code: bool(re.match(r"\s*(?:async\s+)?with\b", code) or ".close()" in code),
    ),
    (
        # Output that is escaped.
        re.compile(r"\bescap(?:es|ed|ing)\b|\bsaniti[sz](?:es|ed|ing|ation)\b", re.IGNORECASE),
        lambda code: bool(re.search(r"\b\w*(?:escape|saniti[sz]e)\w*\s*\(", code)),
    ),
)


def faults_a_safer_change(finding):
    """Does a grounding finding call the change inconsistent for doing the safer thing?"""
    if finding.anchored_by != "evidence" or not _INCONSISTENT.search(finding.message):
        return False
    return any(named.search(finding.message) and uses(finding.evidence) for named, uses in _SAFER)


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
    if finding.agent in NO_SECURITY_CLAIMS and claims_security_defect(finding.message):
        return f"out of scope: {NO_SECURITY_CLAIMS[finding.agent]} making a security claim"
    if finding.agent == "grounding" and faults_a_safer_change(finding):
        return "out of scope: grounding faulting a change for being safer than existing code"
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
        if tool == "ruff" and is_blocking_lint(code):
            return ""  # the file does not parse, or a name it uses does not exist
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
