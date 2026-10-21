"""Real linters over the changed files, run without ever executing repo code.

Spec section 5 wants the static-analysis agent to invoke actual tools rather than ask
a model to guess. That is a security decision as much as a quality one, and it cuts
both ways: running real tools on attacker-controlled code is itself dangerous, so
how they are invoked matters more than which ones.

THE THREAT
A pull request is attacker-controlled. Several popular linters execute code from the
repository as a matter of normal operation:

  - ESLint config files (.eslintrc.js, eslint.config.js) are JavaScript, executed on
    startup. Plugins and `extends` load arbitrary node modules.
  - pyproject.toml / setup.cfg can point tools at plugins that import repo code.
  - `npm install` runs preinstall/postinstall scripts, which is arbitrary execution
    before a linter has even started.

Running any of those against a PR would hand remote code execution to anyone who can
open one.

THE RULES, enforced below
  1. Only file CONTENT is written to a private temp directory. Never a checkout, and
     never anything the repository can nominate as configuration.
  2. `ruff --isolated` ignores every configuration file, including any the attacker
     placed in the tree.
  3. bandit is given our own flags and never `--ini`, so repo settings cannot apply.
  4. No npm, no package manager, no repo script, ever.
  5. Config-shaped files in the diff are not analysed at all.
  6. Subprocesses get a timeout and no shell.

WHY NO ESLINT
Render's docs list node, npm, yarn, pnpm and bun as available in every native
runtime at build and runtime, so ESLint *would* run in production. It is still not
used here, for two reasons. Installing it means `npm install` into the backend image
(~50 MB on a 512 MB dyno) for a linter that - forbidden from loading the repo's
config, plugins and `extends` - would run a bare default ruleset catching little the
security agent does not. And every ESLint integration point that adds real value is
exactly the one that executes repo-controlled JavaScript. JS/TS therefore gets the
pattern pass below, which executes nothing.
"""

import importlib.util
import json
import logging
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
MAX_FILES = 40

# The Python linters, run as `python -m <name>`. Each must be pinned in
# requirements.txt (not only requirements-dev.txt), and a test enforces it.
PYTHON_TOOLS = ("ruff", "bandit")

# Never analysed: these are configuration, and configuration is the attack surface.
CONFIG_NAMES = frozenset(
    {
        "pyproject.toml",
        "setup.cfg",
        "setup.py",
        "tox.ini",
        ".bandit",
        ".flake8",
        "ruff.toml",
        ".ruff.toml",
        ".eslintrc",
        ".eslintrc.js",
        ".eslintrc.cjs",
        ".eslintrc.json",
        ".eslintrc.yml",
        "eslint.config.js",
        "eslint.config.mjs",
        "eslint.config.cjs",
        "package.json",
        "babel.config.js",
        "webpack.config.js",
        "vite.config.js",
        "vite.config.ts",
        "conftest.py",
        "manage.py",
        "Makefile",
        "Dockerfile",
    }
)


@dataclass(frozen=True)
class ToolFinding:
    file: str
    line: int
    code: str
    message: str
    tool: str
    severity: str = "nit"


@dataclass
class AnalysisReport:
    """What static analysis found, and - just as important - what actually ran.

    "0 findings" means nothing unless the reader knows a tool looked. So every tool
    the change needed is accounted for: it ran, or it is named in `unavailable`
    with the reason it did not.
    """

    findings: list = field(default_factory=list)
    ran: list = field(default_factory=list)
    # tool -> why it did not run ("not installed", "timed out", ...)
    unavailable: dict = field(default_factory=dict)

    @property
    def looked(self):
        return bool(self.ran)

    def describe(self):
        """One line for the Agents table: `ran ruff, bandit · skipped: x (why)`."""
        parts = []
        if self.ran:
            parts.append("ran " + ", ".join(self.ran))
        if self.unavailable:
            skipped = ", ".join(f"{tool} ({why})" for tool, why in self.unavailable.items())
            parts.append(f"skipped: {skipped}")
        return " · ".join(parts)


class ToolUnavailable(Exception):
    """A tool could not be run, or produced output that cannot be trusted."""


def tool_command(module):
    """The argv prefix that runs `module` from THIS interpreter, or None.

    Resolved through the running interpreter rather than PATH. A worker started
    without its virtualenv activated has the packages importable but their console
    scripts off PATH, so `shutil.which` reported a tool missing while the comment
    still claimed it ran. Asking the interpreter also ties availability to
    requirements.txt, which is what production installs.
    """
    if importlib.util.find_spec(module) is None:
        return None
    return [sys.executable, "-m", module]


def is_config_file(path):
    name = path.rsplit("/", 1)[-1]
    return name in CONFIG_NAMES or name.startswith(".eslintrc")


# Rules whose verdict depends on the rest of the file: names defined, imported or used
# elsewhere. On a reconstruction from a few hunks that context is missing, so they
# fire on code that is fine - an `import` outside the hunk makes every use look
# undefined (F821), and a use outside it makes the assignment look unused (F841).
PARTIAL_CONTEXT_RULES = frozenset({"F401", "F405", "F811", "F821", "F822", "F823", "F841"})


def is_partial_context_artefact(code):
    """Would this rule only fire because part of the file is missing?"""
    return is_syntax_code(code) or code in PARTIAL_CONTEXT_RULES


def is_syntax_code(code):
    """Is this diagnostic ruff complaining that the file does not parse?

    Modern ruff reports a syntax error as `invalid-syntax`, older versions as E999,
    and a codeless diagnostic is only ever a parse failure - so an empty code counts
    too. Over-matching here loses a style rule at worst; under-matching posts
    "invalid syntax" against code that is fine.
    """
    code = code or ""
    return not code or code.startswith("E9") or "syntax" in code.lower()


def analyse(files, complete=()):
    """Findings only. See `run_analysis` for the full report."""
    return run_analysis(files, complete=complete).findings


def run_analysis(files, complete=()):
    """Run the linters over `{path: content}`; report what ran and what it found.

    `complete` names the paths whose content is a whole file rather than a few
    reconstructed hunks. Syntax diagnostics are kept only for those: part of a file
    does not parse, and saying so describes our reconstruction instead of the pull
    request. Everything not named is treated as partial, because guessing wrong in
    that direction only costs a finding.

    Never raises: a linter that is missing, crashes or hangs costs its findings and
    nothing else.
    """
    report = AnalysisReport()
    analysable = {
        path: content
        for path, content in list(files.items())[:MAX_FILES]
        if content and not is_config_file(path)
    }
    if not analysable:
        return report

    python = {p: c for p, c in analysable.items() if p.endswith((".py", ".pyi"))}
    javascript = {
        p: c for p, c in analysable.items() if p.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs"))
    }

    if python:
        with tempfile.TemporaryDirectory(prefix="codesage-sa-") as workdir:
            written = _write(python, workdir)
            runners = {
                "ruff": lambda: _run_ruff(workdir, written, frozenset(complete)),
                "bandit": lambda: _run_bandit(workdir, written),
            }
            for tool in PYTHON_TOOLS:
                try:
                    report.findings.extend(runners[tool]())
                except ToolUnavailable as exc:
                    report.unavailable[tool] = str(exc)
                else:
                    report.ran.append(tool)

    if javascript:
        report.findings.extend(_scan_javascript(javascript))
        report.ran.append("pattern-scan")

    return report


def _write(files, workdir):
    """Write content into a private temp directory, flattening paths safely.

    Flattened on purpose. Preserving `../` or absolute paths from the diff would let
    a PR write outside the sandbox, and nothing here needs the original tree shape.
    """
    written = {}
    root = Path(workdir)

    for index, (path, content) in enumerate(files.items()):
        safe = f"f{index}_{Path(path).name}"
        target = root / safe
        try:
            target.write_text(content, encoding="utf-8")
        except OSError:
            continue
        written[safe] = path

    return written


def _run(command, cwd):
    """Run a tool with no shell and a timeout. Raises ToolUnavailable on failure."""
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            # shell=False is the default and must stay that way: a filename from a
            # PR must never reach a shell.
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        logger.warning("Static analysis tool timed out: %s", exc)
        raise ToolUnavailable(f"timed out after {TIMEOUT_SECONDS}s") from exc
    except OSError as exc:
        logger.warning("Static analysis tool failed to start: %s", exc)
        raise ToolUnavailable("failed to start") from exc


def _parse_json_output(tool, result):
    """A tool's JSON report, or ToolUnavailable if it did not produce one.

    Both linters print a JSON document even when they find nothing (`[]` for ruff,
    a `results` object for bandit), so empty or unparseable stdout means the tool
    did not do its job - and must not be reported as a clean pass.
    """
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning(
            "%s produced no parseable report (exit %s): %s",
            tool,
            result.returncode,
            str(result.stderr or "")[:500],
        )
        raise ToolUnavailable("produced no report") from exc


def _run_ruff(workdir, written, complete=frozenset()):
    """ruff with --isolated, so no configuration file anywhere can apply."""
    command = tool_command("ruff")
    if command is None:
        raise ToolUnavailable("not installed")

    result = _run(
        [
            *command,
            "check",
            # The security-critical flag: ignore every pyproject.toml, ruff.toml and
            # setup.cfg, including any the pull request added.
            "--isolated",
            "--output-format",
            "json",
            "--select",
            # Bugs and likely defects only. Style rules would drown the review.
            "E9,F,B,S,ASYNC,RUF",
            "--no-cache",
            ".",
        ],
        workdir,
    )
    entries = _parse_json_output("ruff", result)
    if not isinstance(entries, list):
        raise ToolUnavailable("produced no report")

    findings = []
    for entry in entries:
        filename = Path(entry.get("filename", "")).name
        original = written.get(filename)
        if not original:
            continue
        code = entry.get("code") or ""
        if original not in complete and is_partial_context_artefact(code):
            # Only part of this file was available: it was never going to parse, and
            # names defined or used outside the hunks are invisible. Reporting those
            # would describe our own input, not the change.
            continue
        findings.append(
            ToolFinding(
                file=original,
                line=(entry.get("location") or {}).get("row") or 1,
                code=code,
                message=entry.get("message") or "",
                tool="ruff",
                # S = flake8-bandit security rules; E9 = syntax errors.
                severity="blocking" if code.startswith(("S", "E9")) else "nit",
            )
        )
    return findings


def _run_bandit(workdir, written):
    """bandit with our own flags and no --ini, so repo settings cannot apply."""
    command = tool_command("bandit")
    if command is None:
        raise ToolUnavailable("not installed")

    result = _run([*command, "-r", ".", "-f", "json", "-q", "-ll"], workdir)
    payload = _parse_json_output("bandit", result)
    if not isinstance(payload, dict):
        raise ToolUnavailable("produced no report")

    findings = []
    for entry in payload.get("results", []):
        filename = Path(entry.get("filename", "")).name
        original = written.get(filename)
        if not original:
            continue
        confidence = (entry.get("issue_confidence") or "").upper()
        findings.append(
            ToolFinding(
                file=original,
                line=entry.get("line_number") or 1,
                code=entry.get("test_id") or "",
                message=entry.get("issue_text") or "",
                tool="bandit",
                severity="blocking" if confidence == "HIGH" else "nit",
            )
        )
    return findings


# JS/TS patterns. Text matching only - nothing is parsed or executed. Each is
# narrow enough to be worth the false-positive risk; broad "code smell" regexes
# were left out deliberately.
JS_PATTERNS = (
    (
        re.compile(r"\beval\s*\("),
        "js-eval",
        "eval() executes arbitrary code and is almost never necessary.",
        "blocking",
    ),
    (
        re.compile(r"\bnew\s+Function\s*\("),
        "js-new-function",
        "new Function() compiles a string as code, with the same risks as eval().",
        "blocking",
    ),
    (
        re.compile(r"\.innerHTML\s*="),
        "js-inner-html",
        "Assigning to innerHTML with untrusted data is an XSS vector; prefer textContent.",
        "blocking",
    ),
    (
        re.compile(r"\bdocument\.write\s*\("),
        "js-document-write",
        "document.write() is an XSS vector and blocks parsing.",
        "nit",
    ),
    (
        re.compile(r"==\s*(?:null|undefined)\b|\b(?:null|undefined)\s*=="),
        "js-loose-nullish",
        "Loose equality against null/undefined; use === or a nullish check.",
        "nit",
    ),
    (
        re.compile(r"\bcatch\s*\([^)]*\)\s*\{\s*\}"),
        "js-empty-catch",
        "Empty catch block swallows the error silently.",
        "nit",
    ),
)


def _scan_javascript(files):
    """Pattern pass over JS/TS. Executes nothing - see WHY NO ESLINT above."""
    findings = []

    for path, content in files.items():
        for number, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            # Skip obvious comments, so a warning about eval() is not itself flagged.
            if stripped.startswith(("//", "*", "/*")):
                continue
            for pattern, code, message, severity in JS_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        ToolFinding(
                            file=path,
                            line=number,
                            code=code,
                            message=message,
                            tool="pattern-scan",
                            severity=severity,
                        )
                    )
    return findings
