import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";
import { useMemo } from "react";

import { Eyebrow } from "@/components/arbiter/app-shell";
import { LogLine, type LogTone } from "@/components/arbiter/log-line";
import { OutcomeBadge } from "@/components/arbiter/match-archive";
import { Field, FileBlocks, JsonBlock } from "@/components/arbiter/spec-blocks";
import { Button } from "@/components/ui/button";
import { getChallenge, getMatch, listAllMatchEvents } from "@/lib/api";
import type { JsonObject, MatchEventSchema } from "@/lib/dto";
import {
  formatArguments,
  formatDateTime,
  formatDuration,
  formatModel,
} from "@/lib/format";

type DescribedLine = {
  text: string;
  tone: LogTone;
  label: { text: string; tone: LogTone } | null;
  detail: JsonObject | null;
};

/**
 * `/matches?id=<matchId>`: one match's recorded history.
 *
 * Loads the match to get its `challenge_id`, then the full challenge spec and
 * every persisted event. Prisoner and Warden get a box each; system events
 * (match start/finish, traps, sandbox observations) appear in both, in their
 * own colour, so each column reads as a complete timeline.
 */
export function MatchDetails({ matchId }: { matchId: string }) {
  const matchQuery = useQuery({
    queryKey: ["match", matchId],
    queryFn: () => getMatch(matchId),
  });

  const challengeId = matchQuery.data?.challenge_id ?? "";
  const challengeQuery = useQuery({
    queryKey: ["challenge", challengeId],
    queryFn: () => getChallenge(challengeId),
    enabled: challengeId !== "",
  });

  const eventsQuery = useQuery({
    queryKey: ["match-events", matchId],
    queryFn: () => listAllMatchEvents(matchId),
  });

  const match = matchQuery.data ?? null;
  const challenge = challengeQuery.data ?? null;
  const events = eventsQuery.data ?? [];

  const prisonerEvents = useMemo(
    () => eventsForActor(events, "prisoner"),
    [events],
  );
  const wardenEvents = useMemo(
    () => eventsForActor(events, "warden"),
    [events],
  );

  return (
    <main>
      <section className="border-b border-border px-5 py-6 lg:px-8">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-end gap-6">
          <div>
            <p className="text-[11px] font-bold text-primary">
              [RECORDED_MATCH_HISTORY]
            </p>
            <h1 className="mt-3 break-words font-display text-2xl font-bold sm:text-3xl">
              {challenge?.name ?? "Match Details"}
            </h1>
          </div>
          {match !== null && (
            <div className="text-right">
              <div className="text-[10px] text-muted-foreground">OUTCOME</div>
              <div className="mt-2">
                <OutcomeBadge match={match} />
              </div>
            </div>
          )}
          {match !== null && (
            <div className="text-right">
              <div className="text-[10px] text-muted-foreground">DURATION</div>
              <div className="mt-1 text-sm font-bold text-primary">
                {formatDuration(match.duration_seconds)}
              </div>
            </div>
          )}
          {match !== null && (
            <div className="text-right">
              <div className="text-[10px] text-muted-foreground">STARTED</div>
              <div className="mt-1 text-xs text-foreground">
                {formatDateTime(match.started_at ?? match.created_at)}
              </div>
            </div>
          )}
          <Button
            asChild
            variant="ghost"
            size="icon"
            className="ml-auto size-10 rounded-none text-primary hover:bg-transparent hover:text-primary"
          >
            <Link to="/matches" aria-label="Close match details">
              <X className="size-6" strokeWidth={3} />
            </Link>
          </Button>
        </div>

        {matchQuery.isError && (
          <p className="mx-auto mt-4 max-w-[1600px] text-sm text-destructive">
            FAILED TO LOAD MATCH: {(matchQuery.error as Error).message}
          </p>
        )}
      </section>

      {challenge !== null && (
        <section className="border-b border-border bg-panel px-5 py-6 lg:px-8">
          <div className="mx-auto max-w-[1600px]">
            <div className="flex flex-wrap items-baseline gap-3">
              <span className="text-[11px] text-muted-foreground">
                TYPE:{" "}
                <span className="text-primary">{challenge.challenge_type}</span>
              </span>
              {match !== null && (
                <span className="ml-auto text-[11px] text-muted-foreground">
                  {formatModel(match.prisoner_provider, match.prisoner_model)}{" "}
                  vs {formatModel(match.warden_provider, match.warden_model)}
                </span>
              )}
            </div>

            <div className="mt-3 grid gap-x-8 lg:grid-cols-2">
              <div>
                <Field label="DESCRIPTION">
                  <p className="text-xs leading-5 text-muted-foreground">
                    {challenge.description}
                  </p>
                </Field>
                <Field label="WIN_CONDITION">
                  <p className="text-xs leading-5 text-foreground">
                    {challenge.win_condition}
                  </p>
                </Field>
                <Field label="FLAG_STRUCTURE">
                  <JsonBlock value={challenge.flag_structure} />
                </Field>
                <Field label="FLAG (EXPECTED ANSWER)">
                  <JsonBlock value={challenge.flag} />
                </Field>
              </div>
              <div>
                <Field label={`FILES (${Object.keys(challenge.files).length})`}>
                  <FileBlocks files={challenge.files} />
                </Field>
              </div>
            </div>
          </div>
        </section>
      )}

      {challengeQuery.isError && (
        <p className="mx-auto max-w-[1600px] px-5 pt-6 text-sm text-destructive lg:px-8">
          FAILED TO LOAD CHALLENGE: {(challengeQuery.error as Error).message}
        </p>
      )}

      {eventsQuery.isPending && (
        <p className="mx-auto max-w-[1600px] px-5 py-10 text-sm text-muted-foreground lg:px-8">
          LOADING MATCH EVENTS...
        </p>
      )}

      {eventsQuery.isError && (
        <p className="mx-auto max-w-[1600px] px-5 py-10 text-sm text-destructive lg:px-8">
          FAILED TO LOAD EVENTS: {(eventsQuery.error as Error).message}
        </p>
      )}

      {!eventsQuery.isPending && !eventsQuery.isError && (
        <section className="mx-auto grid max-w-[1600px] gap-5 px-5 py-8 lg:grid-cols-2 lg:px-8">
          <EventBox
            title="PRISONER_AGENT"
            role="ATTACKER ROLE"
            model={
              match === null
                ? ""
                : formatModel(match.prisoner_provider, match.prisoner_model)
            }
            events={prisonerEvents}
          />
          <EventBox
            title="WARDEN_AGENT"
            role="DEFENDER ROLE"
            model={
              match === null
                ? ""
                : formatModel(match.warden_provider, match.warden_model)
            }
            events={wardenEvents}
          />
        </section>
      )}
    </main>
  );
}

function EventBox({
  title,
  role,
  model,
  events,
}: {
  title: string;
  role: string;
  model: string;
  events: MatchEventSchema[];
}) {
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
      <div className="event-scroll h-[560px] space-y-3 overflow-y-auto border-l border-primary p-4 text-sm text-foreground sm:p-5">
        {events.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            NO EVENTS RECORDED FOR THIS MATCH.
          </p>
        ) : (
          events.map((event) => {
            const line = describePersistedEvent(event);
            return (
              <LogLine
                key={event.id}
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

/** Actor events plus the system events, interleaved chronologically. */
function eventsForActor(
  events: MatchEventSchema[],
  actor: string,
): MatchEventSchema[] {
  return events
    .filter((event) => event.actor === actor || isSystemEvent(event))
    .sort((a, b) => eventTime(a) - eventTime(b));
}

function isSystemEvent(event: MatchEventSchema): boolean {
  return event.actor !== "prisoner" && event.actor !== "warden";
}

function eventTime(event: MatchEventSchema): number {
  const parsed = new Date(event.timestamp).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

/**
 * Render one persisted `match_events` row. Persisted `event_type` values are
 * the database vocabulary, not the live SSE types. `detail` is what the RESULT
 * toggle expands; the text only ever states the outcome.
 */
function describePersistedEvent(event: MatchEventSchema): DescribedLine {
  const action = event.action;
  const result = event.result ?? {};

  switch (event.event_type) {
    case "chat":
      return {
        text: stringValue(result["content"]) ?? "(empty message)",
        tone: "default",
        label: null,
        detail: null,
      };
    case "tool_call": {
      const tool = stringValue(action["tool"]) ?? "unknown";
      const args = formatArguments(action["arguments"]);
      const success = booleanValue(result["success"]);
      return {
        text: `${tool}${args === "" ? "" : ` (${args})`} -> ${
          success === true ? "OK" : "FAIL"
        }`,
        tone: "default",
        label: { text: "TOOL", tone: success === true ? "success" : "failure" },
        detail: Object.keys(result).length === 0 ? null : result,
      };
    }
    case "sandbox_event": {
      const type = stringValue(action["type"]) ?? "sandbox";
      const detail =
        stringValue(action["path"]) ??
        stringValue(action["process_name"]) ??
        "";
      return {
        text: `SANDBOX ${type.toUpperCase()}${detail === "" ? "" : ` ${detail}`}`,
        tone: "system",
        label: null,
        detail: null,
      };
    }
    case "trap_triggered":
      return {
        text: `TRAP TRIGGERED: ${stringValue(result["trap"]) ?? "unknown"}`,
        tone: "system",
        label: null,
        detail: null,
      };
    case "match_started":
      return {
        text: "MATCH STARTED",
        tone: "system",
        label: null,
        detail: null,
      };
    case "match_finished": {
      const winner = (stringValue(result["winner"]) ?? "none").toUpperCase();
      const reason = stringValue(result["end_reason"]);
      return {
        text: `MATCH FINISHED - WINNER: ${winner}${
          reason === null ? "" : ` (${reason})`
        }`,
        tone: "system",
        label: null,
        detail: null,
      };
    }
    case "agent_retry": {
      const reason = stringValue(result["reason"]) ?? "provider_error";
      const status = numberValue(result["status"]);
      const attempt = numberValue(result["attempt"]);
      const maxAttempts = numberValue(result["max_attempts"]);
      const wait = numberValue(result["wait_seconds"]);
      const label =
        reason === "rate_limit" ? "RATE LIMIT" : "MODEL UNAVAILABLE";
      return {
        text: `${label}${status === null ? "" : ` (${status})`} - retrying in ${
          wait === null ? "?" : wait
        }s (attempt ${attempt ?? "?"}/${maxAttempts ?? "?"})`,
        tone: "emphasis",
        label: null,
        detail: result,
      };
    }
    case "agent_unavailable":
      return {
        text: `MODEL UNAVAILABLE: ${stringValue(result["reason"]) ?? "unknown"}`,
        tone: "failure",
        label: null,
        detail: result,
      };
    case "agent_error":
      return {
        text: `MODEL ERROR (${stringValue(result["reason"]) ?? "unknown"})${
          stringValue(result["detail"]) === null
            ? ""
            : `: ${stringValue(result["detail"])}`
        }`,
        tone: "failure",
        label: null,
        detail: result,
      };
    default:
      return {
        text: event.event_type.toUpperCase(),
        tone: "default",
        label: null,
        detail: null,
      };
  }
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function booleanValue(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

function formatTime(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return "--:--:--";
  return parsed.toLocaleTimeString([], { hour12: false });
}
