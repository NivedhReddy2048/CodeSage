"""Skip-rule tests.

Every file that gets past selection costs Gemini quota to embed and Neon storage to
keep, so these rules are the main free-tier defence. They are also a quality control:
a minified bundle embeds into noise that pollutes retrieval for every real query.
"""

import pytest

from apps.ingestion import selection
from apps.ingestion.selection import SkipReason, build_gitignore_spec, should_skip

SMALL = 1024


@pytest.mark.parametrize(
    "path",
    [
        "node_modules/react/index.js",
        "frontend/node_modules/lodash/map.js",
        "vendor/github.com/pkg/errors.go",
        "dist/main.js",
        "build/output.css",
        ".next/server/page.js",
        "backend/__pycache__/views.cpython-314.pyc",
        ".venv/lib/site-packages/django/db.py",
        "apps/accounts/migrations/0001_initial.py",
    ],
)
def test_generated_and_dependency_directories_are_skipped(path):
    assert should_skip(path, SMALL) == SkipReason.DIRECTORY


@pytest.mark.parametrize(
    "path",
    ["package-lock.json", "frontend/pnpm-lock.yaml", "poetry.lock", "go.sum"],
)
def test_lock_files_are_skipped(path):
    assert should_skip(path, SMALL) == SkipReason.FILENAME


@pytest.mark.parametrize(
    "path",
    ["static/app.min.js", "a/b/style.min.css", "bundle.js.map", "api_pb2.py"],
)
def test_generated_output_is_skipped(path):
    assert should_skip(path, SMALL) == SkipReason.PATTERN


@pytest.mark.parametrize(
    "path", ["docs/logo.png", "fonts/inter.woff2", "data.sqlite3", "secret.pem"]
)
def test_binary_extensions_are_skipped(path):
    assert should_skip(path, SMALL) == SkipReason.EXTENSION


def test_oversized_files_are_skipped(settings):
    settings.INGESTION_MAX_FILE_BYTES = 1000

    assert should_skip("huge.py", 1001) == SkipReason.TOO_LARGE
    assert should_skip("fine.py", 999) is None


def test_empty_files_are_skipped():
    assert should_skip("empty.py", 0) == SkipReason.EMPTY


@pytest.mark.parametrize(
    "path",
    ["app/users.py", "src/components/Button.tsx", "README.md", "Makefile", "go.mod"],
)
def test_real_source_is_kept(path):
    assert should_skip(path, SMALL) is None


# ------------------------------------------------------------------- .gitignore


def test_gitignored_paths_are_skipped():
    """A tarball contains whatever was committed, including committed build output.

    Honouring the repository's own .gitignore respects its opinion about what is
    not source.
    """
    spec = build_gitignore_spec("*.log\nsecrets/\n/local_settings.py\n")

    assert should_skip("debug.log", SMALL, spec) == SkipReason.GITIGNORED
    assert should_skip("secrets/keys.txt", SMALL, spec) == SkipReason.GITIGNORED
    assert should_skip("local_settings.py", SMALL, spec) == SkipReason.GITIGNORED
    assert should_skip("app/views.py", SMALL, spec) is None


def test_gitignore_negation_is_honoured():
    """Negation is exactly the semantics a hand-rolled matcher gets wrong."""
    spec = build_gitignore_spec("*.env\n!.env.example\n")

    assert should_skip("prod.env", SMALL, spec) == SkipReason.GITIGNORED
    assert should_skip(".env.example", SMALL, spec) is None


def test_a_malformed_gitignore_does_not_break_selection():
    spec = build_gitignore_spec("[[[unclosed\n")

    # Either it compiled and matches nothing useful, or it returned None. Both fine;
    # what matters is that selection still works.
    assert should_skip("app/views.py", SMALL, spec) is None


def test_no_gitignore_is_fine():
    assert build_gitignore_spec("") is None
    assert should_skip("app/views.py", SMALL, None) is None


# ----------------------------------------------------------- binary sniffing


def test_null_bytes_mark_content_as_binary():
    assert selection.looks_binary(b"PK\x03\x04\x00\x00data")
    assert not selection.looks_binary(b"def hello():\n    pass\n")


def test_decode_rejects_binary_content():
    assert selection.decode(b"\x00\x01\x02binary") is None


def test_decode_handles_utf8_and_falls_back():
    assert selection.decode("def f(): return 'café'".encode()) is not None
    # Latin-1 bytes that are not valid UTF-8 still decode rather than being dropped.
    assert selection.decode(b"caf\xe9 = 1") is not None


def test_language_detection():
    assert selection.language_for("a/b/users.py") == "python"
    assert selection.language_for("src/App.tsx") == "typescript"
    assert selection.language_for("Makefile") == ""
