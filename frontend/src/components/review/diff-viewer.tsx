"use client";

import { FileCode2 } from "lucide-react";
import { useMemo } from "react";

import { StatusBadge } from "@/components/status-badge";
import { AGENT_LABELS } from "@/lib/format";
import { type DiffFile, type DiffLine, parseDiff } from "@/lib/diff";
import type { ReviewFinding } from "@/lib/types";
import { cn } from "@/lib/utils";

export function lineAnchor(path: string, line: number) {
  return `L-${encodeURIComponent(path)}-${line}`;
}

export function findingAnchor(id: number) {
  return `finding-${id}`;
}

const LINE_TONE: Record<DiffLine["kind"], string> = {
  add: "bg-status-ok-bg/70",
  del: "bg-status-blocking-bg/70",
  context: "",
  note: "text-muted-foreground italic",
};

const LINE_SIGN: Record<DiffLine["kind"], string> = {
  add: "+",
  del: "-",
  context: " ",
  note: "",
};

function InlineFinding({ finding }: { finding: ReviewFinding }) {
  return (
    <div
      id={findingAnchor(finding.id)}
      className="mx-2 my-1.5 scroll-mt-24 rounded-md border bg-card px-3 py-2 font-sans text-sm shadow-xs"
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge kind={finding.severity} />
        {finding.category ? (
          <span className="text-xs text-muted-foreground">{finding.category}</span>
        ) : null}
        <span className="text-xs text-muted-foreground">
          &middot; {AGENT_LABELS[finding.agent] ?? finding.agent}
        </span>
      </div>
      <p className="mt-1 whitespace-pre-wrap">{finding.message}</p>
      {finding.citation ? (
        <p className="mt-1 text-xs text-muted-foreground">
          Grounded in <code>{finding.citation}</code>
        </p>
      ) : null}
    </div>
  );
}

function FileDiff({
  file,
  findingsByLine,
}: {
  file: DiffFile;
  findingsByLine: Map<number, ReviewFinding[]>;
}) {
  const count = [...findingsByLine.values()].reduce((sum, list) => sum + list.length, 0);

  return (
    <section aria-label={`Diff of ${file.path}`} className="overflow-hidden rounded-lg border">
      <header className="flex flex-wrap items-center gap-2 border-b bg-muted/50 px-3 py-2 text-sm">
        <FileCode2 aria-hidden="true" className="size-4 text-muted-foreground" />
        <span className="min-w-0 flex-1 truncate font-mono font-medium">
          {file.status === "renamed" ? `${file.oldPath} → ${file.path}` : file.path}
        </span>
        {file.status !== "modified" ? (
          <span className="text-xs text-muted-foreground capitalize">{file.status}</span>
        ) : null}
        <span className="text-xs tabular-nums text-status-ok">+{file.additions}</span>
        <span className="text-xs tabular-nums text-status-blocking">-{file.deletions}</span>
        {count ? (
          <span className="text-xs text-muted-foreground">
            {count} finding{count === 1 ? "" : "s"}
          </span>
        ) : null}
      </header>
      {file.hunks.length === 0 ? (
        <p className="px-3 py-2 text-sm text-muted-foreground">No textual changes to show.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse font-mono text-xs leading-5">
            <caption className="sr-only">
              Changes to {file.path}, with old and new line numbers
            </caption>
            {file.hunks.map((hunk, hunkIndex) => (
              <tbody key={hunkIndex}>
                <tr className="bg-status-running-bg/50 text-muted-foreground">
                  <td colSpan={3} className="px-3 py-0.5">
                    {hunk.header}
                  </td>
                </tr>
                {hunk.lines.map((line, lineIndex) => {
                  const here = line.newNumber !== null ? findingsByLine.get(line.newNumber) : undefined;
                  return [
                    <tr
                      key={`${hunkIndex}-${lineIndex}`}
                      id={line.newNumber !== null ? lineAnchor(file.path, line.newNumber) : undefined}
                      className={cn(
                        "scroll-mt-24",
                        LINE_TONE[line.kind],
                        here && "outline outline-1 -outline-offset-1 outline-status-blocking/40",
                      )}
                    >
                      <td className="w-12 border-r px-2 text-right text-muted-foreground select-none">
                        {line.oldNumber ?? ""}
                      </td>
                      <td className="w-12 border-r px-2 text-right text-muted-foreground select-none">
                        {line.newNumber ?? ""}
                      </td>
                      <td className="px-2 whitespace-pre">
                        <span aria-hidden="true" className="select-none text-muted-foreground">
                          {LINE_SIGN[line.kind]}
                        </span>
                        <span className="sr-only">
                          {line.kind === "add" ? "added: " : line.kind === "del" ? "removed: " : ""}
                        </span>
                        {line.text}
                      </td>
                    </tr>,
                    here ? (
                      <tr key={`${hunkIndex}-${lineIndex}-findings`}>
                        <td colSpan={3} className="bg-muted/30 py-0.5">
                          {here.map((finding) => (
                            <InlineFinding key={finding.id} finding={finding} />
                          ))}
                        </td>
                      </tr>
                    ) : null,
                  ];
                })}
              </tbody>
            ))}
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * The reviewed diff with each finding threaded under the line it points at. Files
 * with findings come first. A finding whose line the diff does not show cannot be
 * threaded here; `unanchoredFindings` finds those so the panel still lists them.
 */
export function DiffViewer({
  diff,
  findings,
}: {
  diff: string;
  findings: ReviewFinding[];
}) {
  const files = useMemo(() => parseDiff(diff), [diff]);

  const byFile = useMemo(() => {
    const map = new Map<string, Map<number, ReviewFinding[]>>();
    for (const finding of findings) {
      const lines = map.get(finding.file_path) ?? new Map<number, ReviewFinding[]>();
      lines.set(finding.line, [...(lines.get(finding.line) ?? []), finding]);
      map.set(finding.file_path, lines);
    }
    return map;
  }, [findings]);

  const ordered = useMemo(
    () =>
      [...files].sort(
        (a, b) => Number(byFile.has(b.path)) - Number(byFile.has(a.path)),
      ),
    [files, byFile],
  );

  if (files.length === 0) {
    return <p className="text-sm text-muted-foreground">This diff has no file changes to show.</p>;
  }

  return (
    <div className="space-y-4">
      {ordered.map((file) => (
        <FileDiff
          key={`${file.oldPath}->${file.path}`}
          file={file}
          findingsByLine={byFile.get(file.path) ?? new Map()}
        />
      ))}
    </div>
  );
}

/** Findings the diff cannot show inline: their line is not among the visible ones. */
export function unanchoredFindings(diff: string, findings: ReviewFinding[]) {
  const visible = new Map<string, Set<number>>();
  for (const file of parseDiff(diff)) {
    const lines = new Set<number>();
    for (const hunk of file.hunks) {
      for (const line of hunk.lines) if (line.newNumber !== null) lines.add(line.newNumber);
    }
    visible.set(file.path, lines);
  }
  return findings.filter((finding) => !visible.get(finding.file_path)?.has(finding.line));
}
