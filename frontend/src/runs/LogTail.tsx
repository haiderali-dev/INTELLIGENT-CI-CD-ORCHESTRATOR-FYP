import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { useApi } from "@/api/apiClientContext";
import { failureMessage } from "@/api/errors";
import { failureOf } from "@/api/request";
import { runsApi } from "@/api/runsApi";
import { button } from "@/components/button";
import { ExternalLink } from "@/components/ExternalLink";
import { cn } from "@/lib/cn";

import { countLines, keepEnd, lastLines, TAIL_LINES } from "./logModel";

/** How soon to ask again while Jenkins is still writing and nothing new has arrived. */
export const LOG_POLL_MS = 2_000;
/** How soon to ask again when the last window had text: more may already be waiting. */
const LOG_NEXT_MS = 250;

interface LogState {
  /** The end of the log so far, never more than a few hundred lines. */
  text: string;
  lines: number;
  reading: boolean;
  more: boolean;
  error: unknown;
}

const STARTING: LogState = { text: "", lines: 0, reading: true, more: true, error: null };

/**
 * A run's log tail (4.7.3). It reads the console output window by window from the start, keeps
 * the last lines, and while Jenkins is still writing asks again every two seconds, from where it
 * left off. Plex Mono belongs here, in a code view (DESIGN.md section 3).
 */
export function LogTail({
  runId,
  jobName,
  buildNumber,
  url,
}: {
  runId: string;
  jobName: string;
  buildNumber: number;
  url: string | null;
}) {
  const api = useApi(runsApi);
  const [log, setLog] = useState<LogState>(STARTING);
  const [attempt, setAttempt] = useState(0);
  const box = useRef<HTMLPreElement>(null);
  // Follow the end, unless the reader has scrolled up to read something.
  const following = useRef(true);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let offset = 0;
    let text = "";
    let lines = 0;
    setLog(STARTING);

    const read = async () => {
      try {
        const window_ = await api.log(runId, offset);
        if (cancelled) {
          return;
        }
        offset = window_.next_offset;
        lines += countLines(window_.text);
        // Kept short: a long log is never held whole, only its end.
        text = keepEnd(text + window_.text, TAIL_LINES);
        setLog({ text, lines, reading: false, more: window_.more_data, error: null });
        if (window_.more_data) {
          timer = window.setTimeout(() => void read(), window_.text ? LOG_NEXT_MS : LOG_POLL_MS);
        }
      } catch (error) {
        if (!cancelled) {
          setLog((current) => ({ ...current, reading: false, error }));
        }
      }
    };
    void read();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [api, runId, attempt]);

  useLayoutEffect(() => {
    if (box.current && following.current) {
      box.current.scrollTop = box.current.scrollHeight;
    }
  }, [log.text]);

  const shown = lastLines(log.text);
  const shownLines = Math.min(log.lines, TAIL_LINES);
  const label = `Log of ${jobName} #${String(buildNumber)}`;

  return (
    <section aria-label={label} className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="font-semibold">{label}</h3>
        {url ? (
          <ExternalLink href={url} className="text-sm font-semibold">
            Open in Jenkins
          </ExternalLink>
        ) : null}
      </div>
      {log.error ? (
        <div role="alert" className="flex flex-col gap-2 text-sm">
          <p>
            <span className="font-semibold">The log could not be read. </span>
            {failureMessage(failureOf(log.error))}
          </p>
          <button
            type="button"
            onClick={() => {
              setAttempt((count) => count + 1);
            }}
            className={cn(button(), "h-8 self-start px-3 text-sm max-md:h-11")}
          >
            Try again
          </button>
        </div>
      ) : null}
      {shown ? (
        <pre
          ref={box}
          tabIndex={0}
          aria-label={label}
          onScroll={(event) => {
            const element = event.currentTarget;
            following.current =
              element.scrollTop + element.clientHeight >= element.scrollHeight - 4;
          }}
          className="max-h-[28rem] overflow-auto border border-rule bg-ground p-3 text-sm"
        >
          {shown}
        </pre>
      ) : log.reading ? (
        <p className="text-sm text-graphite">Reading the log</p>
      ) : log.error ? null : (
        <p className="text-sm text-graphite">
          {log.more ? "No output yet. The run has not written anything." : "The log is empty."}
        </p>
      )}
      <p aria-live="polite" className="text-sm text-graphite tabular-nums">
        {log.lines > shownLines
          ? `The last ${String(shownLines)} of ${String(log.lines)} lines.`
          : log.lines > 0
            ? `${String(log.lines)} ${log.lines === 1 ? "line" : "lines"}.`
            : ""}
        {log.more && !log.reading && !log.error ? " Still writing." : ""}
      </p>
    </section>
  );
}
