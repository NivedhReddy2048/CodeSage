"""scripts/dev.py, the local dev runner that replaced honcho.

honcho could not stop its children on Windows, and the orphans it left - a Celery
worker running pre-migration code, a runserver holding port 8000 - are what made a
review silently vanish (#79). These tests pin the parts that prevent that: whole
process trees are stopped, stubborn ones are force-killed and named, and the runner
refuses to start while anything could compete with it.
"""

import importlib.util
import io
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import psutil
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev.py"


@pytest.fixture(scope="module")
def dev():
    spec = importlib.util.spec_from_file_location("codesage_dev_runner", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # dataclasses look their module up in sys.modules while the class is built.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture
def printer(dev):
    return dev.Printer(color=False, stream=io.StringIO())


def output(printer):
    return printer.stream.getvalue()


# ------------------------------------------------------------------ what gets run


def test_the_four_processes_and_their_commands(dev):
    specs = {s.name: s for s in dev.build_specs("py", "node", "https://smee.io/abc")}

    assert list(specs) == ["backend", "worker", "frontend", "webhooks"]
    assert specs["backend"].argv == ["py", "manage.py", "runserver", "8000"]
    assert "--pool=solo" in specs["worker"].argv
    assert specs["frontend"].argv[-2:] == ["--port", "3000"]
    assert specs["webhooks"].argv[-4:] == [
        "--url",
        "https://smee.io/abc",
        "--target",
        "http://localhost:8000/api/webhooks/github/",
    ]
    # npm/npx are cmd.exe batch files on Windows; nothing goes through them.
    assert {s.argv[0] for s in specs.values()} == {"py", "node"}


def test_the_smee_channel_comes_from_package_json(dev, tmp_path):
    package = tmp_path / "package.json"
    package.write_text('{"scripts": {"webhooks": "smee --url https://smee.io/xyz --target t"}}')
    assert dev.smee_channel(package) == "https://smee.io/xyz"

    package.write_text('{"scripts": {}}')
    with pytest.raises(SystemExit):
        dev.smee_channel(package)

    assert dev.smee_channel().startswith("https://smee.io/")


def test_children_get_utf8_unbuffered_output_and_no_inherited_port(dev):
    env = dev.child_env({"PATH": "x", "PORT": "5000", "PYTHONIOENCODING": "cp1252"})

    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert "PORT" not in env
    assert env["PATH"] == "x"


def test_each_line_is_prefixed_with_its_process(dev):
    plain = dev.Printer(color=False, stream=io.StringIO())
    plain.line("worker", "35", "celery@host ready.")
    assert plain.stream.getvalue().endswith(" worker   | celery@host ready.\n")

    coloured = dev.Printer(color=True, stream=io.StringIO())
    coloured.line("backend", "36", "hello")
    assert "\x1b[36m" in coloured.stream.getvalue()


# ------------------------------------------------------ recognising leftover processes


@pytest.mark.parametrize(
    ("cmdline", "kind"),
    [
        ("python backend/manage.py runserver 8000", "backend"),
        ("python -m celery -A core --workdir backend worker --pool=solo", "worker"),
        ("node smee.js --url https://smee.io/x", "webhooks"),
        ("npx --yes smee-client --url https://smee.io/x", "webhooks"),
        ("node D:\\CodeSage\\frontend\\node_modules\\next\\dist\\bin\\next dev", "frontend"),
        ("npm --prefix frontend run dev -- --port 3000", "frontend"),
        ("honcho start -f Procfile.dev", "honcho"),
        ("python scripts/dev.py", "dev runner"),
        ("python scripts/dev.py stop", None),
        ("python -m celery -A core inspect ping", None),
        ("python manage.py migrate", None),
    ],
)
def test_dev_processes_are_recognised_by_command_line(dev, cmdline, kind):
    assert dev.classify(cmdline.split()) == kind


def test_only_this_checkouts_processes_count(dev, tmp_path):
    repo = tmp_path / "CodeSage"
    other = tmp_path / "other-project"

    assert dev.belongs_to_repo(["python", "manage.py", "runserver"], str(repo / "backend"), repo)
    assert dev.belongs_to_repo(["node", str(repo / "frontend" / "x.js")], None, repo)
    assert not dev.belongs_to_repo(["python", "manage.py", "runserver"], str(other), repo)
    assert not dev.belongs_to_repo(["python", "manage.py", "runserver"], None, repo)


# ------------------------------------------------------------------------ preflight


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_a_listening_port_counts_as_in_use(dev):
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        port = server.getsockname()[1]
        assert dev.port_in_use(port)
    assert not dev.port_in_use(free_port())


def test_the_broker_address_is_resolved_like_django_settings(dev, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# comment\nREDIS_URL='redis://cache.local:6380/0'\n")

    assert dev.broker_address({}, env_file) == ("cache.local", 6380)
    assert dev.broker_address({"CELERY_BROKER_URL": "redis://b:1/0"}, env_file) == ("b", 1)
    assert dev.broker_address({}, tmp_path / "missing.env") == ("localhost", 6379)


@pytest.mark.parametrize(
    ("returncode", "text", "expected"),
    [
        (0, "->  celery@a: OK\n        pong\n->  celery@a: OK\n        pong\n", ["celery@a"] * 2),
        (69, "Error: No nodes replied within time constraint", []),
        (69, "Error: Could not connect to the message broker.", None),
    ],
)
def test_running_workers_reads_celerys_ping(dev, monkeypatch, returncode, text, expected):
    monkeypatch.setattr(
        dev.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout=text, stderr=""),
    )
    assert dev.running_workers("py", {}) == expected


@pytest.fixture
def clean_preflight(dev, monkeypatch, tmp_path):
    """Everything preflight looks at, set to "all clear"; tests then break one thing."""
    for name in ("VENV_PYTHON", "NEXT_BIN", "SMEE_BIN"):
        path = tmp_path / name
        path.write_text("")
        monkeypatch.setattr(dev, name, path)
    monkeypatch.setattr(dev, "REPO", tmp_path)
    monkeypatch.setattr(dev.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(dev, "find_leftovers", lambda exclude: [])
    monkeypatch.setattr(dev, "BACKEND_PORT", free_port())
    monkeypatch.setattr(dev, "FRONTEND_PORT", free_port())
    monkeypatch.setattr(dev, "reachable", lambda host, port: True)
    monkeypatch.setattr(dev, "running_workers", lambda python, env: [])
    return monkeypatch


def test_preflight_passes_when_nothing_is_in_the_way(dev, printer, clean_preflight):
    assert dev.preflight(printer, "py", {}) == []


def test_preflight_refuses_a_busy_port(dev, printer, clean_preflight):
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        clean_preflight.setattr(dev, "BACKEND_PORT", server.getsockname()[1])

        problems = dev.preflight(printer, "py", {})

    assert len(problems) == 1
    assert "already in use" in problems[0]
    assert "python scripts/dev.py stop" in problems[0]


def test_preflight_refuses_when_a_celery_worker_already_answers(dev, printer, clean_preflight):
    """The incident itself: a second worker would take review tasks with stale code."""
    clean_preflight.setattr(dev, "running_workers", lambda python, env: ["celery@h", "celery@h"])

    problems = dev.preflight(printer, "py", {})

    assert len(problems) == 1
    assert "2 Celery worker(s) already answer" in problems[0]


def test_preflight_refuses_leftover_processes(dev, printer, clean_preflight):
    me = psutil.Process()
    clean_preflight.setattr(dev, "find_leftovers", lambda exclude: [(me, "worker")])

    problems = dev.preflight(printer, "py", {})

    assert any("still running" in p and "python scripts/dev.py stop" in p for p in problems)


def test_preflight_explains_an_unreachable_broker(dev, printer, clean_preflight):
    asked = []
    clean_preflight.setattr(dev, "reachable", lambda host, port: False)
    clean_preflight.setattr(dev, "running_workers", lambda python, env: asked.append(1))

    problems = dev.preflight(printer, "py", {})

    assert "docker compose up -d" in problems[0]
    assert asked == []


def test_nothing_starts_when_preflight_fails(dev, printer, monkeypatch):
    monkeypatch.setattr(dev, "preflight", lambda printer, python, env: ["port 8000 busy"])
    monkeypatch.setattr(dev, "spawn", lambda *a: pytest.fail("must not start anything"))

    assert dev.run(printer) == 2
    assert "not starting" in output(printer)


# ------------------------------------------------------------------------- stopping


TREE = textwrap.dedent(
    """
    import signal, subprocess, sys, time
    stubborn = sys.argv[1] == "stubborn"
    if stubborn:
        for name in ("SIGTERM", "SIGBREAK", "SIGINT"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), signal.SIG_IGN)
    if len(sys.argv) == 2:
        subprocess.Popen([sys.executable, __file__, sys.argv[1], "leaf"])
    else:
        print("leaf up", flush=True)
    time.sleep(120)
    """
)


def start_tree(dev, printer, tmp_path, mode):
    """A child that starts a grandchild, through the runner's own spawn()."""
    script = tmp_path / "tree.py"
    script.write_text(TREE)
    spec = dev.Spec("probe", "0", [sys.executable, str(script), mode], tmp_path)
    child = dev.spawn(spec, dev.child_env(), printer)
    deadline = time.monotonic() + 30
    while "leaf up" not in output(printer):
        assert time.monotonic() < deadline, "the grandchild never started"
        time.sleep(0.1)
    return child


def test_stopping_takes_down_the_whole_tree(dev, printer, tmp_path):
    child = start_tree(dev, printer, tmp_path, "polite")
    tree = dev.process_tree(child.proc.pid)
    assert len(tree) >= 2

    assert dev.stop_children([child], printer, "test", grace=5) is True
    assert dev.survivors(tree) == []


def test_a_process_that_ignores_the_stop_signal_is_force_killed_and_named(dev, printer, tmp_path):
    child = start_tree(dev, printer, tmp_path, "stubborn")
    tree = dev.process_tree(child.proc.pid)

    assert dev.stop_children([child], printer, "test", grace=1) is True
    assert dev.survivors(tree) == []
    assert "force-killed probe" in output(printer)


def test_one_process_exiting_stops_all_of_them(dev, printer, monkeypatch, tmp_path):
    """If the worker dies, the rest must not carry on as if reviews could run."""
    sleeper = tmp_path / "sleeper.py"
    sleeper.write_text("import time\nprint('up', flush=True)\ntime.sleep(120)\n")
    specs = [
        dev.Spec("steady", "0", [sys.executable, str(sleeper)], tmp_path),
        dev.Spec("quitter", "0", [sys.executable, "-c", "import time; time.sleep(1)"], tmp_path),
    ]
    monkeypatch.setattr(dev, "preflight", lambda printer, python, env: [])
    monkeypatch.setattr(dev, "build_specs", lambda python, node, channel: specs)
    monkeypatch.setattr(dev, "smee_channel", lambda: "https://smee.io/x")
    # Not in a test: the job object and process-wide signal handlers outlive the call.
    monkeypatch.setattr(dev, "_join_kill_on_close_job", lambda: True)
    monkeypatch.setattr(dev.signal, "signal", lambda *args: None)

    assert dev.run(printer, grace=5) == 1

    text = output(printer)
    assert "quitter exited with code 0" in text
    assert "stopping steady" in text
    assert not [
        p for p in psutil.process_iter(["cmdline"]) if str(sleeper) in (p.info["cmdline"] or [])
    ]
