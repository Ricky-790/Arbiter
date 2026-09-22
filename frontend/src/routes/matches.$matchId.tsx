import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useMemo, useRef, useState } from "react";

import { LogLine, type LogTone } from "@/components/arbiter/log-line";
import { streamMatchEvents } from "@/lib/api";
import type { JsonObject, SpectateEvent } from "@/lib/dto";
import { formatArguments } from "@/lib/format";

export const Route = createFileRoute("/matches/$matchId")({
  // Search params are optional presentation hints, so a bare match URL still
  // resolves without a redirect.
  validateSearch: (
    search: Record<string, unknown>,
  ): { prisoner?: string; warden?: string; challenge?: string } => {
    const parsed: { prisoner?: string; warden?: string; challenge?: string } =
      {};
    for (const key of ["prisoner", "warden", "challenge"] as const) {
      const value = search[key];
      if (typeof value === "string") parsed[key] = value;
    }
    return parsed;
  },
  head: () => ({
    meta: [
      {
        name: "description",
        content:
          "Watch Prisoner and Warden agents act inside an Arbiter sandbox.",
      },
      { property: "og:title", content: "Spectate Match — Arbiter" },
      {
        property: "og:description",
        content:
          "Watch Prisoner and Warden agents act inside an Arbiter sandbox.",
      },
      { property: "og:type", content: "website" },
      { property: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: SpectatePage,
});

type StreamStatus = "connecting" | "live" | "closed" | "error";

type DescribedLine = {
  text: string;
  tone: LogTone;
  label: { text: string; tone: LogTone } | null;
  detail: JsonObject | null;
};

function SpectatePage() {
  const { matchId } = Route.useParams();
  const { prisoner = "", warden = "", challenge = "" } = Route.useSearch();

  const [events, setEvents] = useState<SpectateEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setEvents([]);
    setStatus("connecting");
    setError(null);

    streamMatchEvents(
      matchId,
      (event) => {
        setEvents((previous) => [...previous, event]);
        if (event.type === "match_finished" || event.type === "stream_closed") {
          setStatus("closed");
        } else {
          setStatus((current) => (current === "closed" ? current : "live"));
        }
      },
      controller.signal,
    )
      .then(() => {
        if (!controller.signal.aborted) {
          setStatus((current) => (current === "error" ? current : "closed"));
        }
      })
      .catch((streamError: unknown) => {
        if (controller.signal.aborted) return;
        setStatus("error");
        setError(
          streamError instanceof Error
            ? streamError.message
            : "Spectator stream failed",
        );
      });

    return () => controller.abort();
  }, [matchId]);

  const prisonerEvents = useMemo(
    () => eventsForActor(events, "prisoner"),
    [events],
  );
  const wardenEvents = useMemo(
    () => eventsForActor(events, "warden"),
    [events],
  );
  const finish = useMemo(
    () =>
      [...events].reverse().find((event) => event.type === "match_finished") ??
      null,
    [events],
  );

  return (
    <main>
      <section className="border-b border-border px-5 py-6 lg:px-8">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-end gap-6">
          <div>
            <p className="text-[11px] font-bold text-primary">
              {statusLabel(status)}
            </p>
            <h1 className="mt-3 break-words font-display text-2xl font-bold sm:text-3xl">
              {challenge === "" ? "Sandbox Run" : challenge}
            </h1>
          </div>
          <div className="ml-auto text-right">
            <div className="text-[10px] text-muted-foreground">EVENTS</div>
            <div className="mt-1 text-2xl font-bold text-primary">
              {events.length}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] text-muted-foreground">RESULT</div>
            <div className="mt-2 text-sm font-bold text-primary">
              {finish === null
                ? "IN PROGRESS"
                : `${(finish.winner ?? "unknown").toString().toUpperCase()}${
                    finish.end_reason ? ` · ${finish.end_reason}` : ""
                  }`}
            </div>
          </div>
        </div>
        {error !== null && (
          <p className="mx-auto mt-4 max-w-[1600px] text-sm text-destructive">
            STREAM ERROR: {error}
          </p>
        )}
      </section>

      <section className="mx-auto grid max-w-[1600px] gap-5 px-5 py-8 lg:grid-cols-2 lg:px-8">
        <ActorStream
          title="PRISONER_AGENT"
          role="ATTACKER ROLE"
          model={prisoner}
          events={prisonerEvents}
        />
        <ActorStream
          title="WARDEN_AGENT"
          role="DEFENDER ROLE"
          model={warden}
          events={wardenEvents}
        />
      </section>
    </main>
  );
}

function ActorStream({
  title,
  role,
  model,
  events,
}: {
  title: string;
  role: string;
  model: string;
  events: SpectateEvent[];
}) {
  const scroller = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = scroller.current;
    if (node !== null) node.scrollTop = node.scrollHeight;
  }, [events.length]);

  return (
    <section className="data-panel border-b-primary">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-panel-raised px-4 py-4 text-xs font-bold">
        <span className="text-primary">{title}</span>
        {model !== "" && (
          <span className="break-all text-muted-foreground">{model}</span>
        )}
        <span className="ml-auto text-[11px] text-muted-foreground">
          {role}
        </span>
      </header>
      <div
        ref={scroller}
        className="event-scroll h-[560px] space-y-3 overflow-y-auto border-l border-primary p-4 text-sm text-foreground sm:p-5"
      >
        {events.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            AWAITING {title} ACTIVITY...
          </p>
        ) : (
          events.map((event, index) => {
            const line = describeEvent(event);
            return (
              <LogLine
                key={`${event.type}-${index}`}
                time={formatTime(event.timestamp)}
                text={line.text}
                tone={line.tone}
                label={line.label}
                detail={line.detail}
              />
            );
          })
        )}
      </div>
    </section>
  );
}

/**
 * Actor events plus the match-wide system events, interleaved
 * chronologically. Transport events (`stream_*`) are not match events, so
 * they stay out of the boxes.
 */
function eventsForActor(
  events: SpectateEvent[],
  actor: string,
): SpectateEvent[] {
  return events
    .filter(
      (event) =>
        event.actor === actor ||
        (event.actor !== "prisoner" &&
          event.actor !== "warden" &&
          !event.type.startsWith("stream_")),
    )
    .sort((a, b) => eventTime(a) - eventTime(b));
}

function eventTime(event: SpectateEvent): number {
  if (event.timestamp === undefined) return 0;
  const parsed = new Date(event.timestamp).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

function describeEvent(event: SpectateEvent): DescribedLine {
  switch (event.type) {
    case "match_started":
      return {
        text: "MATCH STARTED",
        tone: "system",
        label: null,
        detail: null,
      };
    case "agent_message":
      return {
        text: event.content ?? "",
        tone: "default",
        label: null,
        detail: null,
      };
    case "tool_result": {
      const args = formatArguments(event.arguments);
      return {
        text: `${event.tool ?? "unknown"}${
          args === "" ? "" : ` (${args})`
        } -> ${event.success === true ? "OK" : "FAIL"}`,
        tone: "default",
        label: {
          text: "TOOL",
          tone: event.success === true ? "success" : "failure",
        },
        detail: {
          success: event.success ?? null,
          exit_code: event.exit_code ?? null,
          error: event.error ?? null,
        },
      };
    }
    case "trap_triggered":
      return {
        text: `TRAP TRIGGERED: ${event.trap ?? "unknown"}`,
        tone: "system",
        label: null,
        detail: null,
      };
    case "match_finished":
      return {
        text: `MATCH FINISHED - WINNER: ${(event.winner ?? "none")
          .toString()
          .toUpperCase()}${event.end_reason ? ` (${event.end_reason})` : ""}`,
        tone: "system",
        label: null,
        detail: null,
      };
    case "agent_retry": {
      const label =
        event.reason === "rate_limit" ? "RATE LIMIT" : "MODEL UNAVAILABLE";
      return {
        text: `${label}${event.status === undefined ? "" : ` (${event.status})`} - retrying in ${
          event.wait_seconds ?? "?"
        }s (attempt ${event.attempt ?? "?"}/${event.max_attempts ?? "?"})`,
        tone: "emphasis",
        label: null,
        detail: { ...event },
      };
    }
    case "agent_unavailable":
      return {
        text: `MODEL UNAVAILABLE: ${event.reason ?? "unknown"}`,
        tone: "failure",
        label: null,
        detail: { ...event },
      };
    case "agent_error":
      return {
        text: `MODEL ERROR (${event.reason ?? "unknown"})${
          event.detail === undefined ? "" : `: ${event.detail}`
        }`,
        tone: "failure",
        label: null,
        detail: { ...event },
      };
    case "stream_error":
      return {
        text: "SPECTATOR STREAM ERROR",
        tone: "failure",
        label: null,
        detail: null,
      };
    default:
      return {
        text: event.type.toUpperCase(),
        tone: "default",
        label: null,
        detail: null,
      };
  }
}

function formatTime(timestamp: string | undefined): string {
  if (timestamp === undefined) return "--:--:--";
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return "--:--:--";
  return parsed.toLocaleTimeString([], { hour12: false });
}

function statusLabel(status: StreamStatus): string {
  switch (status) {
    case "connecting":
      return "[SPECTATOR_SHELL_CONNECTING]";
    case "live":
      return "[SPECTATOR_SHELL_ACTIVE]";
    case "closed":
      return "[SPECTATOR_STREAM_CLOSED]";
    case "error":
      return "[SPECTATOR_STREAM_ERROR]";
  }
}
