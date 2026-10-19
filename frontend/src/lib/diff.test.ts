import { describe, expect, it } from "vitest";

import { parseDiff, visibleLines } from "@/lib/diff";

const MODIFIED = `diff --git a/app/users.py b/app/users.py
index 1111111..2222222 100644
--- a/app/users.py
+++ b/app/users.py
@@ -10,6 +10,8 @@ def helper():
 def paginate_users(users, page, per_page=10):
     start = (page - 1) * per_page
-    end = start + per_page
+    end = page + per_page
+    query = "SELECT * FROM users WHERE name = '%s'" % users
     return users[start:end]
`;

const ADDED_AND_DELETED = `diff --git a/app/lookup.py b/app/lookup.py
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/app/lookup.py
@@ -0,0 +1,2 @@
+def lookup(x):
+    return x
diff --git a/old.txt b/old.txt
deleted file mode 100644
--- a/old.txt
+++ /dev/null
@@ -1 +0,0 @@
-gone
\\ No newline at end of file
`;

describe("parseDiff", () => {
  it("numbers lines in both files the way GitHub does", () => {
    const [file] = parseDiff(MODIFIED);
    const lines = file.hunks[0].lines;

    expect(file.path).toBe("app/users.py");
    expect(file.status).toBe("modified");
    expect(lines.map((l) => [l.kind, l.oldNumber, l.newNumber])).toEqual([
      ["context", 10, 10],
      ["context", 11, 11],
      ["del", 12, null],
      ["add", null, 12],
      ["add", null, 13],
      ["context", 13, 14],
    ]);
    expect([file.additions, file.deletions]).toEqual([2, 1]);
  });

  it("the SQL-injection line the testbed review flagged lands on new line 13", () => {
    const [file] = parseDiff(MODIFIED);
    const line = file.hunks[0].lines.find((l) => l.newNumber === 13);

    expect(line?.text).toContain("SELECT * FROM users");
  });

  it("recognises added and deleted files, and the no-newline marker", () => {
    const [added, deleted] = parseDiff(ADDED_AND_DELETED);

    expect(added.status).toBe("added");
    expect(added.path).toBe("app/lookup.py");
    expect(added.hunks[0].lines.map((l) => l.newNumber)).toEqual([1, 2]);

    expect(deleted.status).toBe("deleted");
    expect(deleted.path).toBe("old.txt");
    expect(deleted.hunks[0].lines.map((l) => l.kind)).toEqual(["del", "note"]);
  });

  it("removed lines are never a place a finding can sit", () => {
    const [file] = parseDiff(MODIFIED);

    expect([...visibleLines(file)].sort((a, b) => a - b)).toEqual([10, 11, 12, 13, 14]);
  });

  it("handles a rename", () => {
    const [file] = parseDiff(
      "diff --git a/a.py b/b.py\nsimilarity index 90%\nrename from a.py\nrename to b.py\n",
    );
    expect([file.status, file.oldPath, file.path]).toEqual(["renamed", "a.py", "b.py"]);
  });

  it("keeps a real blank context line at the end of a hunk", () => {
    const [file] = parseDiff("--- a/x.py\n+++ b/x.py\n@@ -1,2 +1,2 @@\n-a\n+b\n \n");

    expect(file.hunks[0].lines.map((l) => [l.kind, l.newNumber])).toEqual([
      ["del", null],
      ["add", 1],
      ["context", 2],
    ]);
  });

  it("returns nothing for an empty diff", () => {
    expect(parseDiff("")).toEqual([]);
  });
});
