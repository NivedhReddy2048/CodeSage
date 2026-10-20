// No "use client": it holds no state and only memoises, so the landing page renders
// its example on the server with nothing to hydrate. The review page, a client
// component, still bundles it as client code.

import { BookOpenCheck, FileCode2 } from "lucide-react";
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

// Added and removed lines are tinted with the success and blocking fills, whose
// text pairs are in the contrast test, and also carry a coloured sign and a
// screen-reader word - never colour alone.
const LINE_TONE: Record<DiffLine["kind"], string> = {
  add: "bg-status-ok-bg",
  del: "bg-status-blocking-bg",
  context: "",
  note: "text-fg-secondary italic",
};

const SIGN_TONE: Record<DiffLine["kind"], string> = {
  add: "text-status-ok",
  del: "text-status-blocking",
  context: "text-fg-secondary",
  note: "text-fg-secondary",
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
      className={cn(
        "sticky left-2 my-1.5 w-[calc(100cqw-1rem)] scroll-mt-24 rounded-lg border border-l-[3px] bg-surface-1 px-3 py-2 font-sans text-sm whitespace-normal shadow-card",
        finding.severity === "blocking" ? "border-l-status-blocking" : "border-l-status-nit",
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge kind={finding.severity} />
        <span className="rounded-md border bg-surface-2 px-1.5 py-0.5 text-xs font-medium text-fg-secondary">
          {AGENT_LABELS[finding.agent] ?? finding.agent}
        </span>
        {finding.category ? (
          <span className="text-xs text-fg-secondary">{finding.category}</span>
        ) : null}
      </div>
      <p className="mt-1.5 whitespace-pre-wrap text-fg">{finding.message}</p>
      {finding.citation ? (
        <p className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-fg-secondary">
          <BookOpenCheck aria-hidden="true" className="size-3.5 text-brand" />
          Grounded in
          <code className="rounded-md border border-border-brand bg-brand-tinted px-1.5 py-0.5 font-mono text-[0.6875rem] text-brand">
            {finding.citation}
          </code>
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
    // overflow-clip, not hidden: clip does not make a scroll container, so the file
    // header can stick to the page (under the 56px top bar) while its file scrolls by.
    <section aria-label={`Diff of ${file.path}`} className="overflow-clip rounded-xl border bg-surface-1 shadow-card">
      <header className="sticky top-14 z-10 flex flex-wrap items-center gap-2 border-b bg-surface-2 px-3 py-2 text-sm">
        <FileCode2 aria-hidden="true" className="size-4 text-fg-secondary" />
        <span className="min-w-0 flex-1 truncate font-mono text-[0.8125rem] font-medium text-fg">
          {file.status === "renamed" ? `${file.oldPath} → ${file.path}` : file.path}
        </span>
        {file.status !== "modified" ? (
          <span className="rounded-md border bg-surface-1 px-1.5 py-0.5 text-[0.6875rem] text-fg-secondary capitalize">{file.status}</span>
        ) : null}
        <span className="font-mono text-xs tabular-nums text-status-ok">+{file.additions}</span>
        <span className="font-mono text-xs tabular-nums text-status-blocking">-{file.deletions}</span>
        {count ? (
          <span className="text-xs text-fg-secondary">
            {count} finding{count === 1 ? "" : "s"}
          </span>
        ) : null}
      </header>
      {file.hunks.length === 0 ? (
        <p className="px-3 py-2 text-sm text-fg-secondary">No textual changes to show.</p>
      ) : (
        // A size container: an inline finding takes the visible width (100cqw) and
        // stays put while long code lines scroll sideways beneath it.
        <div className="@container overflow-x-auto">
          <table className="w-full border-collapse font-mono text-xs leading-5">
            <caption className="sr-only">
              Changes to {file.path}, with old and new line numbers
            </caption>
            {file.hunks.map((hunk, hunkIndex) => (
              <tbody key={hunkIndex}>
                <tr className="bg-surface-2/70 text-fg-secondary">
                  <td colSpan={3} className="px-3 py-1">
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
                        here && "outline outline-1 -outline-offset-1 outline-status-blocking-border",
                      )}
                    >
                      <td className="w-12 border-r px-2 text-right text-fg-secondary tabular-nums select-none">
                        {line.oldNumber ?? ""}
                      </td>
                      <td className="w-12 border-r px-2 text-right text-fg-secondary tabular-nums select-none">
                        {line.newNumber ?? ""}
                      </td>
                      <td className="px-2 whitespace-pre text-fg">
                        <span aria-hidden="true" className={cn("mr-1 select-none font-semibold", SIGN_TONE[line.kind])}>
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
                        <td colSpan={3} className="bg-surface-2/50 py-0.5">
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
    return <p className="text-sm text-fg-secondary">This diff has no file changes to show.</p>;
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
