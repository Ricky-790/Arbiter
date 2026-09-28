import { useState } from "react";

import type { JsonObject } from "@/lib/dto";

export type LogTone = "default" | "emphasis" | "system" | "success" | "failure";

const TONE_CLASS: Record<LogTone, string> = {
  default: "log-text",
  emphasis: "log-text emphasis",
  system: "log-text system",
  success: "log-text success",
  failure: "log-text failure",
};

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
    <div className="log-line">
      <span className="log-time">{time}</span>
      <div className="log-copy">
        <span className={TONE_CLASS[tone]}>
          {label != null && (
            <span className={`log-label ${TONE_CLASS[label.tone]}`}>
              {label.text}
            </span>
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
              className="log-toggle"
              aria-expanded={expanded}
            >
              [{expanded ? "hide result" : "result"}]
            </button>
            {expanded && (
              <pre className="log-detail">
                {JSON.stringify(detail, null, 2)}
              </pre>
            )}
          </>
        )}
      </div>
    </div>
  );
}
