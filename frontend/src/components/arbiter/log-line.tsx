import { useState } from "react";

import type { JsonObject } from "@/lib/dto";

/** How one log row is coloured. */
export type LogTone = "default" | "emphasis" | "system" | "success" | "failure";

const TONE_CLASS: Record<LogTone, string> = {
  default: "text-foreground",
  emphasis: "font-bold text-primary",
  system: "text-[#7dd3fc]",
  success: "font-bold text-[#4ade80]",
  failure: "font-bold text-[#f87171]",
};

/**
 * One timestamped log row.
 *
 * `label` renders a short coloured prefix (e.g. TOOL in green/red) while
 * `tone` colours the rest of the line (system events use their own colour).
 * `detail` is never shown inline: the row carries the outcome, and the raw
 * payload stays collapsed behind a RESULT toggle until the reader asks.
 */
export function LogLine({
  time,
  text,
  tone = "default",
  label,
  detail,
}: {
  time: string;
  text: string;
  tone?: LogTone;
  label?: { text: string; tone: LogTone } | null;
  detail: JsonObject | null;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="grid grid-cols-[70px_1fr] gap-2 text-sm leading-5">
      <span className="pt-0.5 text-[11px] text-muted-foreground">{time}</span>
      <div>
        <span className={TONE_CLASS[tone]}>
          {label != null && (
            <span className={TONE_CLASS[label.tone]}>{label.text}</span>
          )}
          {label != null ? " " : ""}
          {text}
        </span>
        {detail !== null && (
          <>
            {" "}
            <button
              type="button"
              onClick={() => setExpanded((value) => !value)}
              className="text-[10px] text-muted-foreground underline-offset-2 hover:text-primary hover:underline"
            >
              [{expanded ? "HIDE RESULT" : "RESULT"}]
            </button>
            {expanded && (
              <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all border border-border bg-background p-2 text-[11px] leading-4 text-muted-foreground">
                {JSON.stringify(detail, null, 2)}
              </pre>
            )}
          </>
        )}
      </div>
    </div>
  );
}
