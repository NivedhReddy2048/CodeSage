/**
 * Unified-diff parsing for the review page's diff viewer.
 *
 * Findings are anchored to (file, line in the NEW file), the same coordinates the
 * backend validates them against, so every line here carries its new-file number.
 * Removed lines have none: a finding can never point at code that no longer exists.
 */

export type DiffLineKind = "add" | "del" | "context" | "note";

export type DiffLine = {
  kind: DiffLineKind;
  oldNumber: number | null;
  newNumber: number | null;
  text: string;
};

export type DiffHunk = { header: string; lines: DiffLine[] };

export type DiffFileStatus = "added" | "deleted" | "modified" | "renamed" | "binary";

export type DiffFile = {
  path: string;
  oldPath: string;
  status: DiffFileStatus;
  hunks: DiffHunk[];
  additions: number;
  deletions: number;
};

const HUNK = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/;

function stripPrefix(path: string) {
  return path.replace(/^[ab]\//, "");
}

export function parseDiff(text: string): DiffFile[] {
  const files: DiffFile[] = [];
  let file: DiffFile | null = null;
  let hunk: DiffHunk | null = null;
  let oldNumber = 0;
  let newNumber = 0;

  const startFile = (path = "", oldPath = "") => {
    file = { path, oldPath, status: "modified", hunks: [], additions: 0, deletions: 0 };
    files.push(file);
    hunk = null;
    return file;
  };

  const rows = text.split("\n");
  // Text that ends in a newline splits into one trailing "" that is not a line.
  if (rows.at(-1) === "") rows.pop();

  for (const raw of rows) {
    if (raw.startsWith("diff --git ")) {
      const match = /^diff --git a\/(.+) b\/(.+)$/.exec(raw);
      startFile(match?.[2] ?? "", match?.[1] ?? "");
      continue;
    }

    const current: DiffFile | null = file;
    if (current === null) {
      // A bare diff with no "diff --git" header still starts at "--- a/...".
      if (raw.startsWith("--- ")) startFile();
      else continue;
    }
    const target = file as unknown as DiffFile;

    if (hunk === null) {
      if (raw.startsWith("new file mode")) target.status = "added";
      else if (raw.startsWith("deleted file mode")) target.status = "deleted";
      else if (raw.startsWith("rename from ")) {
        target.status = "renamed";
        target.oldPath = raw.slice("rename from ".length);
      } else if (raw.startsWith("rename to ")) target.path = raw.slice("rename to ".length);
      else if (raw.startsWith("Binary files ")) target.status = "binary";
      else if (raw.startsWith("--- ")) {
        const old = raw.slice(4).trim();
        if (old !== "/dev/null") target.oldPath = stripPrefix(old);
        else target.status = "added";
      } else if (raw.startsWith("+++ ")) {
        const next = raw.slice(4).trim();
        if (next === "/dev/null") target.status = "deleted";
        else target.path = stripPrefix(next);
      }
      if (!raw.startsWith("@@")) continue;
    }

    const header = HUNK.exec(raw);
    if (header) {
      oldNumber = Number(header[1]);
      newNumber = Number(header[2]);
      hunk = { header: raw, lines: [] };
      target.hunks.push(hunk);
      continue;
    }

    const lines = (hunk as unknown as DiffHunk).lines;
    if (raw.startsWith("+")) {
      lines.push({ kind: "add", oldNumber: null, newNumber, text: raw.slice(1) });
      newNumber += 1;
      target.additions += 1;
    } else if (raw.startsWith("-")) {
      lines.push({ kind: "del", oldNumber, newNumber: null, text: raw.slice(1) });
      oldNumber += 1;
      target.deletions += 1;
    } else if (raw.startsWith("\\")) {
      lines.push({ kind: "note", oldNumber: null, newNumber: null, text: raw.slice(2) });
    } else if (raw.startsWith(" ") || raw === "") {
      // A bare "" inside a hunk is a blank context line whose leading space an
      // editor or copy-paste stripped.
      lines.push({ kind: "context", oldNumber, newNumber, text: raw.slice(1) });
      oldNumber += 1;
      newNumber += 1;
    }
  }

  for (const parsed of files) {
    if (!parsed.oldPath) parsed.oldPath = parsed.path;
  }
  return files;
}

/** Every new-file line number the diff shows for a path - where a finding can sit. */
export function visibleLines(file: DiffFile) {
  const numbers = new Set<number>();
  for (const hunk of file.hunks) {
    for (const line of hunk.lines) if (line.newNumber !== null) numbers.add(line.newNumber);
  }
  return numbers;
}
