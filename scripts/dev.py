#!/usr/bin/env python3
"""Run the whole local CodeSage stack from one terminal, and stop all of it.

    python scripts/dev.py           start backend, worker, frontend and webhook relay
    python scripts/dev.py stop      kill leftover CodeSage dev processes (emergencies)

This replaced honcho, which cannot stop its children on Windows: on Ctrl+C it loops
"sending SIGKILL" to no effect, then crashes and leaves every process running. Those
orphans are how a Celery worker started days earlier, with code older than a
migration, took a review and crashed on it (#79), and how a stale runserver kept
port 8000 so the current one never served a request.

So this runner:

- starts each child in its own process group (Windows) or session (Unix), so the
  child and everything it spawns can be signalled together;
- stops gracefully first - CTRL_BREAK_EVENT on Windows, SIGTERM on Unix - and after
  GRACE_SECONDS force-kills whatever is left of each tree, naming it;
- on Windows, puts itself in a kill-on-close job object that every child inherits,
  so even if the runner is killed outright, Windows ends the whole tree;
- refuses to start while anything could compete with it: ports 8000/3000 in use, a
  Celery worker already answering on the broker, or leftover dev processes.

Needs psutil (backend/requirements-dev.txt). Run with any Python: without psutil it
re-runs itself under backend/.venv, so no virtualenv activation is needed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

try:
    import psutil
except ImportError:  # handled in main(): re-run under the backend virtualenv
    psutil = None

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
FRONTEND = REPO / "frontend"
WINDOWS = os.name == "nt"
VENV_PYTHON = BACKEND / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")

BACKEND_PORT = 8000
FRONTEND_PORT = 3000
WEBHOOK_TARGET = f"http://localhost:{BACKEND_PORT}/api/webhooks/github/"
# How long each process gets to exit on its own before its tree is force-killed.
GRACE_SECONDS = 8
# After this long without every process ready, say which ones are still starting.
READY_WARNING_SECONDS = 180

NEXT_BIN = FRONTEND / "node_modules" / "next" / "dist" / "bin" / "next"
SMEE_BIN = FRONTEND / "node_modules" / "smee-client" / "bin" / "smee.js"


# --------------------------------------------------------------------- process specs


@dataclass
class Spec:
    """One process of the stack, and how to tell it has finished starting."""

    name: str
    color: str  # ANSI SGR code
    argv: list[str]
    cwd: Path
    ready_pattern: re.Pattern | None = None  # matched against its output
    ready_port: int | None = None  # or: ready once this port accepts connections


def smee_channel(package_json=FRONTEND / "package.json"):
    """The smee.io channel, read from the `webhooks` script so it is defined once."""
    scripts = json.loads(Path(package_json).read_text(encoding="utf-8")).get("scripts", {})
    match = re.search(r"--url\s+(\S+)", scripts.get("webhooks", ""))
    if not match:
        raise SystemExit("frontend/package.json has no `webhooks` script with --url <channel>")
    return match.group(1)


def build_specs(python, node, channel):
    """The four processes. Node tools run as `node <script>`, not through npm/npx.

    npm and npx are batch files on Windows. Running them means cmd.exe in the middle
    of the tree, which answers Ctrl+Break with "Terminate batch job (Y/N)?" instead
    of exiting, and is one more parent that can die first and orphan its children.
    """
    return [
        Spec(
            "backend",
            "36",
            [python, "manage.py", "runserver", str(BACKEND_PORT)],
            BACKEND,
            ready_port=BACKEND_PORT,
        ),
        Spec(
            "worker",
            "35",
            # --pool=solo: Celery's default prefork pool does not work on Windows; it
            # accepts tasks and never runs them.
            [python, "-m", "celery", "-A", "core", "worker", "--loglevel=info", "--pool=solo"],
            BACKEND,
            ready_pattern=re.compile(r"celery@\S+ ready\."),
        ),
        Spec(
            "frontend",
            "32",
            # The port is explicit: the OAuth callback and the CORS allowlist both name
            # localhost:3000, and Next.js would otherwise honour any inherited PORT.
            [node, str(NEXT_BIN), "dev", "--port", str(FRONTEND_PORT)],
            FRONTEND,
            ready_port=FRONTEND_PORT,
        ),
        Spec(
            "webhooks",
            "33",
            [node, str(SMEE_BIN), "--url", channel, "--target", WEBHOOK_TARGET],
            FRONTEND,
            ready_pattern=re.compile(r"Connected to "),
        ),
    ]


def child_env(base=None):
    """The environment every child gets.

    PYTHONIOENCODING: a cp1252 console cannot encode the non-ASCII glyphs Next.js and
    Celery print. PYTHONUNBUFFERED: a piped Python child would otherwise hold its log
    lines back until a buffer fills.
    """
    env = dict(os.environ if base is None else base)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("PORT", None)
    return env


# --------------------------------------------------------------------------- output


def use_color(stream=None):
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not stream.isatty():
        return False
    return _enable_windows_ansi() if WINDOWS else True


def _enable_windows_ansi():
    """Turn on ANSI escape handling in a Windows console (off by default in conhost)."""
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
    mode = ctypes.c_uint32()
    if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        return False
    return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))  # VT processing


class Printer:
    """Serialises lines from every reader thread, each prefixed with its process."""

    WIDTH = 8

    def __init__(self, color=False, stream=None):
        self.color = color
        self.stream = stream or sys.stdout
        self.lock = threading.Lock()

    def prefix(self, name, color):
        label = f"{time.strftime('%H:%M:%S')} {name:<{self.WIDTH}} |"
        return f"\x1b[{color}m{label}\x1b[0m " if self.color else f"{label} "

    def line(self, name, color, text):
        with self.lock:
            self.stream.write(self.prefix(name, color) + text + "\n")
            self.stream.flush()

    def dev(self, text):
        self.line("dev", "1", text)


# ------------------------------------------------------------------ process helpers


def own_lineage():
    """This process and its ancestors: never matched as leftovers, never killed."""
    me = psutil.Process()
    return {me.pid, *(parent.pid for parent in me.parents())}


def _normalise(text):
    return text.replace("\\", "/").lower()


def classify(cmdline):
    """Which kind of CodeSage dev process a command line is, or None."""
    joined = _normalise(" ".join(cmdline))
    if "manage.py" in joined and "runserver" in joined:
        return "backend"
    if "celery" in joined and re.search(r"\bworker\b", joined):
        return "worker"
    if "smee" in joined:
        return "webhooks"
    if "node_modules/next/" in joined or "run dev" in joined or "next dev" in joined:
        return "frontend"
    if "honcho" in joined:
        return "honcho"
    if "scripts/dev.py" in joined and "stop" not in joined.split():
        return "dev runner"
    return None


def belongs_to_repo(cmdline, cwd, repo=REPO):
    """Whether a process is this checkout's: its command line or directory says so.

    Without this, `stop` would kill another project's runserver or Next.js.
    """
    root = _normalise(str(repo))
    return root in _normalise(" ".join(cmdline)) or bool(cwd and _normalise(cwd).startswith(root))


def find_leftovers(exclude):
    """[(process, kind)] for every CodeSage dev process running from this checkout."""
    found = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        if proc.pid in exclude:
            continue
        cmdline = proc.info["cmdline"] or []
        kind = classify(cmdline)
        if kind is None:
            continue
        try:
            cwd = proc.cwd()
        except (psutil.Error, OSError):
            cwd = None
        if belongs_to_repo(cmdline, cwd):
            found.append((proc, kind))
    return found


def describe(proc):
    try:
        cmdline = " ".join(proc.cmdline())
    except (psutil.Error, OSError):
        cmdline = "?"
    cmdline = " ".join(cmdline.replace(str(REPO), ".").split())
    if len(cmdline) > 110:
        cmdline = cmdline[:107] + "..."
    return f"pid {proc.pid:<6} {cmdline}"


def process_tree(pid):
    """A process and all its descendants, as psutil handles (pid-reuse safe)."""
    try:
        root = psutil.Process(pid)
        return [root, *root.children(recursive=True)]
    except psutil.Error:
        return []


def survivors(procs):
    alive = []
    for proc in procs:
        try:
            if proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE:
                alive.append(proc)
        except psutil.Error:
            pass
    return alive


def signal_gracefully(pid):
    """Ask a child's whole group to exit. False if the signal could not be sent."""
    try:
        if WINDOWS:
            # Delivered to every process in the child's group (its pid is the group
            # id, from CREATE_NEW_PROCESS_GROUP). Needs a console shared with it.
            os.kill(pid, signal.CTRL_BREAK_EVENT)
        else:
            os.killpg(pid, signal.SIGTERM)
        return True
    except (OSError, ProcessLookupError):
        return False


def force_kill(pid, procs):
    """Kill a tree outright, plus any remembered descendant it no longer reaches.

    A tree kill walks parent links, so a grandchild whose parent already exited is
    invisible to it. Those are exactly the orphans this runner exists to prevent, so
    every process seen in the tree before shutdown is also killed by pid.
    """
    if WINDOWS:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    for proc in procs:
        try:
            proc.kill()
        except psutil.Error:
            pass


def _names(procs):
    labels = []
    for proc in procs:
        try:
            labels.append(f"{proc.name()} {proc.pid}")
        except psutil.Error:
            labels.append(str(proc.pid))
    return ", ".join(labels)


def _join_kill_on_close_job():
    """Put this process in a job object that kills every member when it closes.

    Children inherit the job, and the handle closes when this process ends however it
    ends - Ctrl+C, a crash, the console window closed, Task Manager. The explicit
    shutdown below still runs first; this is the backstop. Returns False if Windows
    refused (it should not: nested jobs are allowed since Windows 8).
    """
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in ("Reads", "Writes", "Others", "ReadBytes", "WriteBytes", "OtherBytes")
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return False
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    extended_limit_information = 9
    if not kernel32.SetInformationJobObject(
        job, extended_limit_information, ctypes.byref(limits), ctypes.sizeof(limits)
    ):
        return False
    # The handle is deliberately never closed: it must live exactly as long as we do.
    _join_kill_on_close_job.handle = job
    return bool(kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()))


# ------------------------------------------------------------------------ preflight


def port_in_use(port):
    """Whether anything listens on, or holds, a local port.

    Connecting catches a listener; binding catches a socket that is bound but not
    accepting - a hung server still blocks the port. SO_REUSEADDR on Unix only so
    the bind test ignores TIME_WAIT left by the previous run; on Windows the same
    option would let the test steal a port that is genuinely in use.
    """
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.5)
                if probe.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if not WINDOWS:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return True
    return False


def port_owners(port):
    """Pids listening on a port. macOS needs root for this, so it falls back to lsof."""
    try:
        return sorted(
            {
                conn.pid
                for conn in psutil.net_connections(kind="tcp")
                if conn.laddr and conn.laddr.port == port and conn.status == psutil.CONN_LISTEN
                if conn.pid
            }
        )
    except (psutil.AccessDenied, OSError):
        pass
    if shutil.which("lsof"):
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
        )
        return sorted({int(pid) for pid in result.stdout.split() if pid.isdigit()})
    return []


def read_env_file(path):
    values = {}
    if not Path(path).exists():
        return values
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def broker_address(environ=None, env_file=BACKEND / ".env"):
    """(host, port) of the Celery broker, resolved the way Django settings resolve it."""
    environ = os.environ if environ is None else environ
    from_file = read_env_file(env_file)
    url = (
        environ.get("CELERY_BROKER_URL")
        or from_file.get("CELERY_BROKER_URL")
        or environ.get("REDIS_URL")
        or from_file.get("REDIS_URL")
        or "redis://localhost:6379/0"
    )
    parsed = urlparse(url)
    return parsed.hostname or "localhost", parsed.port or 6379


def reachable(host, port, timeout=2.0):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def running_workers(python, env):
    """Names of Celery workers answering a ping on the broker; None if the ask failed."""
    try:
        result = subprocess.run(
            [python, "-m", "celery", "-A", "core", "inspect", "ping", "--timeout", "2"],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = result.stdout + result.stderr
    if result.returncode == 0:
        return re.findall(r"->\s+(\S+?):\s", output) or ["(unnamed worker)"]
    if "No nodes replied" in output:
        return []
    return None


def preflight(printer, python, env):
    """Everything that must be true before starting. Returns the problems found."""
    problems = []
    for path, fix in (
        (VENV_PYTHON, "create backend/.venv and pip install -r backend/requirements-dev.txt"),
        (NEXT_BIN, "run: npm --prefix frontend install"),
        (SMEE_BIN, "run: npm --prefix frontend install"),
    ):
        if not path.exists():
            problems.append(f"{path.relative_to(REPO)} is missing - {fix}")
    if not shutil.which("node"):
        problems.append("node is not on PATH - install Node.js")

    leftovers = find_leftovers(own_lineage())
    if leftovers:
        listing = "\n".join(f"    {kind:<10} {describe(proc)}" for proc, kind in leftovers)
        problems.append(
            "CodeSage dev processes from an earlier run are still running:\n"
            f"{listing}\n"
            "  Stop them with:  python scripts/dev.py stop"
        )

    for port in (BACKEND_PORT, FRONTEND_PORT):
        if not port_in_use(port):
            continue
        owners = [psutil.Process(pid) for pid in port_owners(port) if psutil.pid_exists(pid)]
        held_by = "\n".join(f"    {describe(proc)}" for proc in owners) or "    (owner unknown)"
        problems.append(
            f"Port {port} is already in use:\n{held_by}\n"
            "  If that is a leftover CodeSage process:  python scripts/dev.py stop\n"
            "  Otherwise stop that program first."
        )

    host, port = broker_address()
    if not reachable(host, port):
        problems.append(
            f"The Celery broker (Redis) at {host}:{port} is not reachable.\n"
            "  Start it with:  docker compose up -d"
        )
    elif not problems:
        # Only asked when everything else is clear: it takes a few seconds, and a
        # worker found by the leftover scan above is already reported.
        printer.dev("asking the broker whether any Celery worker is already running...")
        workers = running_workers(python, env)
        if workers is None:
            problems.append(
                "Could not ask the broker for running Celery workers "
                f"(`celery -A core inspect ping` failed against {host}:{port})."
            )
        elif workers:
            problems.append(
                f"{len(workers)} Celery worker(s) already answer on the broker: "
                f"{', '.join(sorted(set(workers)))}.\n"
                "  A second worker would compete for review tasks, possibly running stale\n"
                "  code. Stop it first: python scripts/dev.py stop (for one on this machine),\n"
                "  or stop it wherever it runs."
            )
    return problems


# ------------------------------------------------------------------------ the runner


@dataclass
class Child:
    spec: Spec
    proc: subprocess.Popen
    ready: bool = False
    reader: threading.Thread | None = field(default=None, repr=False)


def spawn(spec, env, printer):
    kwargs = {
        "cwd": spec.cwd,
        "env": env,
        # Never the console's stdin: a child reading it would steal keystrokes, and
        # cmd.exe's "Terminate batch job (Y/N)?" would wait on it forever.
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
    }
    if WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    child = Child(spec, subprocess.Popen(spec.argv, **kwargs))

    def pump():
        for raw in iter(child.proc.stdout.readline, b""):
            text = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            printer.line(spec.name, spec.color, text)
            if spec.ready_pattern and spec.ready_pattern.search(text):
                child.ready = True
        child.proc.stdout.close()

    child.reader = threading.Thread(target=pump, name=f"read-{spec.name}", daemon=True)
    child.reader.start()
    return child


def stop_children(children, printer, reason, grace=GRACE_SECONDS):
    """Graceful stop, then force-kill what is left. True when nothing survives."""
    names = ", ".join(c.spec.name for c in children if c.proc.poll() is None) or "nothing"
    printer.dev(f"{reason} - stopping {names}")

    # Every descendant, remembered now: one whose parent exits first becomes an orphan
    # that a tree kill rooted at the parent can no longer find.
    trees = {c.spec.name: process_tree(c.proc.pid) for c in children}

    signalled = [c for c in children if c.proc.poll() is None and signal_gracefully(c.proc.pid)]
    deadline = time.monotonic() + grace
    try:
        while signalled and time.monotonic() < deadline:
            for c in children:
                c.proc.poll()  # reap, so an exited child is not counted as alive
            if not any(survivors(trees[c.spec.name]) for c in children):
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        printer.dev("interrupted again - force-killing now")

    forced = []
    for c in children:
        c.proc.poll()
        remaining = survivors(trees[c.spec.name] + process_tree(c.proc.pid))
        if remaining:
            label = _names(remaining)
            force_kill(c.proc.pid, remaining)
            forced.append(c.spec.name)
            printer.dev(f"force-killed {c.spec.name} (did not exit within {grace}s): {label}")

    end = time.monotonic() + 5
    left = []
    while time.monotonic() < end:
        for c in children:
            c.proc.poll()
        left = [p for c in children for p in survivors(trees[c.spec.name])]
        if not left:
            break
        time.sleep(0.2)
    for c in children:
        if c.reader:
            c.reader.join(timeout=2)

    if left:
        printer.dev(f"could not stop: {_names(left)}")
        return False
    if forced:
        printer.dev(f"stopped; {len(forced)} needed a force-kill ({', '.join(forced)})")
    else:
        printer.dev("stopped; every process exited gracefully")
    return True


def _raise_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt


def run(printer, grace=GRACE_SECONDS):
    python = str(VENV_PYTHON)
    env = child_env()

    printer.dev("checking ports 8000/3000, the broker and leftover processes...")
    problems = preflight(printer, python, env)
    if problems:
        printer.dev("not starting:")
        for problem in problems:
            for line in ("  x " + problem).splitlines():
                printer.dev(line)
        return 2

    if WINDOWS:
        # Windows children inherit "Ctrl+C disabled" from whatever started them - an
        # IDE task runner or an agent's shell - even across a new console. Without
        # this, Ctrl+C would do nothing here and the stack could not be stopped.
        import ctypes

        ctypes.windll.kernel32.SetConsoleCtrlHandler(None, False)

    # Ctrl+Break, a closed terminal or `kill` all shut down the same way as Ctrl+C.
    for name in ("SIGBREAK", "SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _raise_keyboard_interrupt)

    if WINDOWS and not _join_kill_on_close_job():
        printer.dev("note: could not create a kill-on-close job; relying on explicit stop")

    children = []
    started = time.monotonic()
    announced = warned = False
    reason, code = None, 0
    try:
        for spec in build_specs(python, shutil.which("node") or "node", smee_channel()):
            child = spawn(spec, env, printer)
            children.append(child)
            command = " ".join(spec.argv).replace(str(REPO), ".")
            printer.dev(f"started {spec.name} (pid {child.proc.pid}): {command}")

        while reason is None:
            for child in children:
                returncode = child.proc.poll()
                if returncode is not None:
                    reason, code = f"{child.spec.name} exited with code {returncode}", 1
                    break
                port = child.spec.ready_port
                if port and not child.ready and port_in_use(port):
                    child.ready = True
            elapsed = time.monotonic() - started
            if not announced and all(c.ready for c in children):
                announced = True
                printer.dev(
                    f"all {len(children)} processes ready in {elapsed:.1f}s - "
                    f"backend http://localhost:{BACKEND_PORT}, "
                    f"frontend http://localhost:{FRONTEND_PORT}. Ctrl+C stops everything."
                )
            elif not announced and not warned and elapsed > READY_WARNING_SECONDS:
                warned = True
                waiting = ", ".join(c.spec.name for c in children if not c.ready)
                printer.dev(f"still waiting for: {waiting}")
            time.sleep(0.25)
    except KeyboardInterrupt:
        reason, code = "Ctrl+C", 0

    clean = stop_children(children, printer, reason, grace)
    return code if clean else 1


def stop(printer):
    """Kill every leftover CodeSage dev process, found by command line and by port."""
    exclude = own_lineage()
    targets = {proc.pid: (proc, kind) for proc, kind in find_leftovers(exclude)}
    for port in (BACKEND_PORT, FRONTEND_PORT):
        for pid in port_owners(port):
            if pid not in exclude and pid not in targets and pid > 4:
                try:
                    targets[pid] = (psutil.Process(pid), f"port {port}")
                except psutil.Error:
                    pass

    if targets:
        printer.dev(f"stopping {len(targets)} process(es):")
        for proc, kind in targets.values():
            printer.dev(f"  {kind:<10} {describe(proc)}")
        everything = []
        for pid in targets:
            everything.extend(process_tree(pid))
        if not WINDOWS:
            for proc in everything:
                try:
                    proc.terminate()
                except psutil.Error:
                    pass
            psutil.wait_procs(everything, timeout=3)
        for pid in targets:
            force_kill(pid, survivors(everything))
        psutil.wait_procs(everything, timeout=5)
    else:
        printer.dev("no CodeSage dev processes found")

    left = find_leftovers(own_lineage())
    busy = [port for port in (BACKEND_PORT, FRONTEND_PORT) if port_in_use(port)]
    for proc, kind in left:
        printer.dev(f"still running: {kind} {describe(proc)}")
    for port in busy:
        printer.dev(f"port {port} is still in use")
    if left or busy:
        return 1
    printer.dev("done: no CodeSage dev processes left; ports 8000 and 3000 are free")
    return 0


def main(argv=None):
    if psutil is None:
        # Re-run under the backend virtualenv, which has psutil. This process just
        # waits; the console's Ctrl+C reaches the re-run copy directly.
        if VENV_PYTHON.exists() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            if hasattr(signal, "SIGBREAK"):
                signal.signal(signal.SIGBREAK, signal.SIG_IGN)
            return subprocess.call([str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])
        return "psutil is missing: pip install -r backend/requirements-dev.txt"

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", nargs="?", default="start", choices=["start", "stop"])
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    printer = Printer(color=use_color())
    return stop(printer) if args.command == "stop" else run(printer)


if __name__ == "__main__":
    sys.exit(main())
