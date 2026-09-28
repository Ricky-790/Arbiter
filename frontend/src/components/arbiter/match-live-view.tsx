import { useEffect, useMemo, useRef, useState } from "react";

import { MatchMasthead } from "@/components/arbiter/match-masthead";
import { LogLine, type LogTone } from "@/components/arbiter/log-line";
import { streamMatchEvents } from "@/lib/api";
import type { JsonObject, MatchListSchema, SpectateEvent } from "@/lib/dto";
import { formatArguments, formatModel } from "@/lib/format";

type StreamStatus = "connecting" | "live" | "closed" | "error";

type DescribedLine = {
  text: string;
  tone: LogTone;
  label: { text: string; tone: LogTone } | null;
  detail: JsonObject | null;
};

/**
 * The live half of the unified match view.
 *
 * The match row arrives as a prop from `MatchView`, which has already waited
 * out the `queued`/`pending` phase, so this only ever opens the stream once the
 * backend is actually hosting the match. Reaches here only for
 * `starting`/`running` rows.
 */
export function MatchLiveView({ match }: { match: MatchListSchema }) {
  const [events, setEvents] = useState<SpectateEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setEvents([]);
    setStatus("connecting");
    setError(null);

    streamMatchEvents(
      match.id,
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
  }, [match.id]);

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
      <MatchMasthead
        eyebrow={`Live spectator / stream ${match.id.slice(0, 8)}`}
        title={match.challenge_name ?? "Sandbox run"}
        status={
          <span className={`board-status ${statusTone(status)}`}>
            {statusLabel(status)}
          </span>
        }
        metrics={[
          {
            label: "Events received",
            value: events.length.toString().padStart(2, "0"),
            signal: true,
          },
          {
            label: "Result",
            value:
              finish === null
                ? "In progress"
                : `${(finish.winner ?? "unknown").toString().toUpperCase()}${
                    finish.end_reason ? ` · ${finish.end_reason}` : ""
                  }`,
          },
          { label: "Match ID", value: match.id },
        ]}
        error={
          error === null ? undefined : (
            <p className="match-error">Stream error: {error}</p>
          )
        }
      />

      <section className="page-wrap event-section">
        <div className="event-grid">
          <ActorStream
            title="PRISONER_AGENT"
            role="Attacker role"
            tone="prisoner"
            model={formatModel(match.prisoner_provider, match.prisoner_model)}
            events={prisonerEvents}
          />
          <ActorStream
            title="WARDEN_AGENT"
            role="Defender role"
            tone="warden"
            model={formatModel(match.warden_provider, match.warden_model)}
            events={wardenEvents}
          />
        </div>
      </section>
    </main>
  );
}

function ActorStream({
  title,
  role,
  tone,
  model,
  events,
}: {
  title: string;
  role: string;
  tone: "prisoner" | "warden";
  model: string;
  events: SpectateEvent[];
}) {
  const scroller = useRef<HTMLDivElement | null>(null);
  const pinnedToBottom = useRef(true);

  useEffect(() => {
    const node = scroller.current;
    // Only follow the stream when the reader is already at the bottom, so
    // scrolling back through history is not yanked away on every frame.
    if (node !== null && pinnedToBottom.current) {
      node.scrollTop = node.scrollHeight;
    }
  }, [events.length]);

  return (
    <section className={`event-panel ${tone}`}>
      <header className="event-panel-header">
        <span className="event-panel-name">{title}</span>
        {model !== "" && <span className="event-panel-model">{model}</span>}
        <span className="event-panel-role">{role}</span>
      </header>
      <div
        ref={scroller}
        className="event-stream event-scroll"
        onScroll={(event) => {
          const node = event.currentTarget;
          pinnedToBottom.current =
            node.scrollHeight - node.scrollTop - node.clientHeight < 24;
        }}
      >
        {events.length === 0 ? (
          <p className="event-empty">Awaiting {title} activity...</p>
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
      return "Connecting";
    case "live":
      return "Connected";
    case "closed":
      return "Closed";
    case "error":
      return "Error";
  }
}

/** A settled or broken stream must not keep the live blink going. */
function statusTone(status: StreamStatus): string {
  switch (status) {
    case "live":
      return "is-live";
    case "error":
      return "is-error";
    case "connecting":
    case "closed":
      return "is-idle";
  }
}
