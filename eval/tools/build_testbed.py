"""Stage testbed cases (DEV: PRs #1-#3, #5-#8; TEST: PR #4) and the 7 new TEST cases.

All use retrieval against the testbed index at INDEX (= testbed main). Usage:
python build_testbed.py <stage>
"""

import difflib
import json
import subprocess
import sys
from pathlib import Path

REPO = "NivedhReddy2048/codesage-testbed"
INDEX = "8934446375efcce89bb47fa88454c2bb4946cd67"


def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout


def file_at(ref, path):
    return gh("api", f"repos/{REPO}/contents/{path}?ref={ref}", "-H", "Accept: application/vnd.github.raw")


def new_file_diff(path, content):
    lines = content.splitlines(keepends=True)
    body = "".join("+" + line for line in lines)
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n{body}"
    )


def modified_diff(path, before, after):
    body = "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True), f"a/{path}", f"b/{path}", n=3
        )
    )
    return f"diff --git a/{path} b/{path}\n{body}"


def write(stage, case, diff, snapshots=None):
    case_dir = Path(stage) / case["suite"] / case["id"]
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "diff.patch").write_text(diff, encoding="utf-8", newline="\n")
    for path, content in (snapshots or {}).items():
        target = case_dir / "files" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="")
    (case_dir / "case.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")


def case(cid, suite, language, title, bugs, *, kind="testbed", pr=0, head="", clean=False, notes="", **source):
    return {
        "id": cid,
        "suite": suite,
        "language": language,
        "clean": clean,
        "source": {"kind": kind, "url": f"https://github.com/{REPO}" + (f"/pull/{pr}" if pr else ""), **source},
        "context": {"full_name": REPO, "pr_number": pr, "title": title, "base_branch": "main", "head_sha": head},
        "retrieval": {"repository": REPO, "index_commit": INDEX},
        "bugs": bugs,
        "notes": notes,
    }


def bug(bid, path, lines, category, note):
    return {"id": bid, "file": path, "lines": lines, "category": category, "kind": "added", "note": note}


def testbed_prs(stage):
    """Real testbed PRs: the diff GitHub shows, head snapshots for modified files."""
    prs = {
        1: ("dev", "python", [
            bug("syntax", "test.py", [1, 1], "correctness", "Every line is indented by 4 spaces: the file does not parse."),
            bug("off-by-one", "test.py", [3, 3], "correctness", "range(len(users) + 1) reads past the end (IndexError)."),
        ]),
        2: ("dev", "javascript", [
            bug("missing-await", "web/orders.js", [8, 9], "concurrency", "fetchOrder is async; order is a Promise, so order.id is undefined."),
        ]),
        3: ("dev", "python", [
            bug("duplicate", "app/lookup.py", [4, 12], "other", "lookup_user reimplements UserRepository.find_by_id (app/users.py:15-20)."),
        ]),
        4: ("test", "python", [
            bug("hard-coded-key", "app/reports.py", [3, 3], "security", "A live API key committed to source."),
            bug("unclosed-connection", "app/reports.py", [7, 11], "resource-leak", "conn is opened and never closed."),
            bug("sql-injection", "app/reports.py", [9, 10], "security", "customer_name is interpolated into the SQL string."),
            bug("division-by-zero", "app/reports.py", [18, 18], "error-handling", "An empty orders list divides by zero."),
            bug("missing-not-found", "app/reports.py", [28, 29], "error-handling", "find_customer returns None for an unknown email; it is indexed straight away."),
        ]),
        5: ("dev", "python", []),
        6: ("dev", "python", []),
        7: ("dev", "python", []),
    }
    for pr, (suite, language, bugs) in prs.items():
        meta = json.loads(gh("api", f"repos/{REPO}/pulls/{pr}"))
        diff = gh("pr", "diff", str(pr), "-R", REPO)
        modified = [f["filename"] for f in json.loads(gh("api", f"repos/{REPO}/pulls/{pr}/files")) if f["status"] == "modified"]
        notes = "Testbed PR; seen during development." if suite == "dev" else (
            "Testbed PR #4, the original five planted bugs (two known misses). In TEST as "
            "decided, though it was reviewed live during development."
        )
        if not bugs:
            notes = "Clean testbed PR (a fix with no new bug); seen during development."
        write(
            stage,
            case(f"testbed-pr{pr}", suite, language, meta["title"], bugs, pr=pr, head=meta["head"]["sha"],
                 clean=not bugs, notes=notes, base_commit=meta["base"]["sha"]),
            diff,
            {path: file_at(meta["head"]["sha"], path) for path in modified},
        )
    # PR #8 at its two commits: the first does not parse; the second is clean.
    base = json.loads(gh("api", f"repos/{REPO}/pulls/8"))["base"]["sha"]
    for sha, cid, bugs, clean, note in (
        ("f701890", "testbed-pr8-f701890", [bug("syntax", "app/money.py", [1, 1], "correctness",
         "Every line of the new file is indented by 3 spaces: the file does not parse.")], False,
         "Testbed PR #8, first commit."),
        ("584b17d", "testbed-pr8-584b17d", [], True,
         "Testbed PR #8 at its final commit: clean. The grounding nit (Decimal vs the integer-cents "
         "pattern in app/models.py:19-28) is a fair consistency remark, not a bug."),
    ):
        diff = gh("api", f"repos/{REPO}/compare/{base}...{sha}", "-H", "Accept: application/vnd.github.v3.diff")
        write(stage, case(cid, "dev", "python", "Add money helper functions to handle decimals", bugs,
                          pr=8, head=sha, clean=clean, notes=note, base_commit=base), diff)


PLANTED = {
    "planted-refund-dollars": ("python", "app/refunds.py", '''"""Refunds for cancelled or partly returned orders."""


def apply_refund(order, amount):
    """Take a refund off an order. `amount` is what the customer gets back, in dollars."""
    if amount <= 0:
        raise ValueError("a refund must be positive")
    order.total_cents -= amount
    order.status = "refunded" if order.total_cents <= 0 else "partially_refunded"
    return order
''', [bug("units", "app/refunds.py", [8, 8], "correctness",
          "Subtracts dollars from total_cents (app/models.py: Order.total_cents is integer cents).")],
     "Grounding: the units are only clear from the existing Order model."),
    "planted-signup-email": ("python", "app/signup.py", '''"""Self-service sign-up."""

import re

from app.models import User


def looks_like_email(value):
    return re.match(r".+@.+", value or "") is not None


def sign_up(users, user_id, email, display_name):
    if not looks_like_email(email):
        raise ValueError("invalid email address")
    return users.add(User(id=user_id, email=email, display_name=display_name))
''', [bug("duplicate-validation", "app/signup.py", [8, 9], "other",
          "Reimplements app/validators.py is_valid_email with a weaker pattern, and skips normalise_email.")],
     "Grounding: the existing validator is in app/validators.py."),
    "planted-admin-renamed": ("python", "app/admin.py", '''"""Admin operations."""


def suspend_user(users, user_id):
    """Deactivate a user from the admin console."""
    user = users.get_by_id(user_id)
    if user is None:
        return False
    user.is_active = False
    return True
''', [bug("no-such-method", "app/admin.py", [6, 6], "correctness",
          "UserRepository has find_by_id, not get_by_id: AttributeError on every call.")],
     "Grounding: only the existing UserRepository shows the method's real name."),
    "planted-order-permission": ("python", "app/order_edit.py", '''"""Editing orders."""


def update_order_status(user, order, status):
    """Change an order's status. Only its owner or an administrator may do this."""
    if not (user.is_active or order.user_id == user.id):
        raise PermissionError("you may not edit this order")
    order.status = status
    return order
''', [bug("wrong-permission", "app/order_edit.py", [6, 7], "security",
          "Any active user passes the check; app/auth.py user_can_edit_order is the real rule.")],
     "Planted wrong permission check."),
    "planted-profile-null": ("javascript", "web/profile.js", '''import { findUserById } from "./users";

export function profileHeading(users, userId) {
  const user = findUserById(users, userId);
  return `${user.displayName} <${user.email}>`;
}
''', [bug("missing-null-check", "web/profile.js", [4, 5], "error-handling",
          "findUserById (Array.find) returns undefined for an unknown id; user.displayName then throws.")],
     "Planted missing null check."),
    "planted-export-leak": ("javascript", "web/exporter.js", '''import fs from "fs";

export function exportOrders(path, orders) {
  const fd = fs.openSync(path, "w");
  for (const order of orders) {
    if (!order.id) {
      throw new Error("order without an id");
    }
    fs.writeSync(fd, `${order.id},${order.totalCents}\\n`);
  }
  fs.closeSync(fd);
}
''', [bug("fd-leak", "web/exporter.js", [4, 11], "resource-leak",
          "The descriptor is never closed when the loop throws (no try/finally).")],
     "Planted resource leak."),
}

CHANGE_EMAIL = '''
    def change_email(self, user_id, email):
        """Let a user change their email address."""
        user = self.users.find_by_id(user_id)
        if user is None:
            return False
        user.email = email
        return True
'''


def planted(stage):
    for cid, (language, path, content, bugs, note) in PLANTED.items():
        write(stage, case(cid, "test", language, f"Add {path}", bugs, kind="planted", head=INDEX,
                          notes=note + " Written for TEST before any DEV run."), new_file_diff(path, content))
    before = file_at(INDEX, "app/service.py")
    after = before.rstrip("\n") + "\n" + CHANGE_EMAIL
    diff = modified_diff("app/service.py", before, after)
    start = after.splitlines().index("    def change_email(self, user_id, email):") + 1
    write(stage, case("planted-change-email", "test", "python", "Let users change their email", [
        bug("skips-validation", "app/service.py", [start + 5, start + 5], "correctness",
            "Stores the new email unvalidated and un-normalised, unlike register (is_valid_email, normalise_email).")],
        kind="planted", head=INDEX, notes="Grounding: register() in the same class shows the rule. "
        "Written for TEST before any DEV run."), diff, {"app/service.py": after})


stage = sys.argv[1]
testbed_prs(stage)
planted(stage)
print("ok")
