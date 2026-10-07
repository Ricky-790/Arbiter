import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { X } from "lucide-react";
import { lazy, Suspense, useMemo, useState } from "react";
import { toast } from "sonner";

import {
  EventGroup,
  type DescribedLine,
} from "@/components/arbiter/event-group";
import { MatchStats } from "@/components/arbiter/match-stats";
import { OutcomeBadge } from "@/components/arbiter/outcome-badge";
import { MatchMasthead } from "@/components/arbiter/match-masthead";
import { Field } from "@/components/arbiter/spec-blocks";
import { forkMatch, getMatchSummary, listAllMatchEvents } from "@/lib/api";
import type {
  MatchEventSchema,
  MatchListSchema,
  MatchSummaryResponse,
} from "@/lib/dto";
import {
  formatArguments,
  formatDateTime,
  formatDuration,
  formatModel,
} from "@/lib/format";
import {
  eventsForActor,
  groupEventsByBatch,
  type EventGroup as EventTurn,
} from "@/lib/match-events";
import { canFork } from "@/lib/match-status";

const NO_EVENTS: MatchEventSchema[] = [];
const NO_SUMMARIES: MatchSummaryResponse[] = [];
const NO_SIDES: Record<string, MatchSummaryResponse | undefined> = {};

/**
 * The dialog (and the Radix alert-dialog it composes) is only pulled in once
 * someone actually asks to fork, so the transcript itself does not carry it.
 */
const ForkDialog = lazy(() =>
  import("@/components/arbiter/fork-dialog").then((module) => ({
    default: module.ForkDialog,
  })),
);

/**
 * A settled match: what was played, what each side spent, and both transcripts.
 *
 * `MatchView` only routes here once the row is out of its live statuses, and it
 * owns the match row itself, so this view fetches the reviewer's summary — which
 * carries the challenge brief and both sides' totals — and the event history.
 * Nothing here needs polling: the row is already terminal.
 */
export function MatchDetails({ match }: { match: MatchListSchema }) {
  const queryClient = useQueryClient();
  const [forkTarget, setForkTarget] = useState<EventTurn | null>(null);

  // The summary always answers with a list, one entry per side, so this asks for
  // both and lets each entry carry its own stats and strategy.
  const summaryQuery = useQuery({
    queryKey: ["match-summary", match.id],
    queryFn: () => getMatchSummary(match.id),
  });

  const eventsQuery = useQuery({
    queryKey: ["match-events", match.id],
    queryFn: () => listAllMatchEvents(match.id),
  });

  // Every entry repeats the same match row, so the first one speaks for all of
  // them. `null` until the call lands, and `[]` is all it can ever be otherwise.
  const entries = summaryQuery.data ?? NO_SUMMARIES;
  const overview = entries[0] ?? null;
  const events = eventsQuery.data ?? NO_EVENTS;

  const fork = useMutation({
    mutationFn: (eventId: string) =>
      forkMatch({ parent_match_id: match.id, match_event_id: eventId }),
    onSuccess: async (response) => {
      // A fork is a checkpoint, not a match: nothing runs, so the transcript
      // stays where it is and the new point is only worth announcing.
      await queryClient.invalidateQueries({ queryKey: ["forks"] });
      setForkTarget(null);
      if (response.status === "ready") {
        toast.success("Fork point ready", {
          description: "This point was already saved, so it is ready to run.",
        });
      } else {
        toast.success("Fork point queued", {
          description:
            "Rebuilding the sandbox snapshot and both conversations. Find it in the Forks tab when it is ready.",
        });
      }
    },
    onError: (error) => {
      toast.error("Could not save the fork point", {
        description: error instanceof Error ? error.message : "Request failed",
      });
    },
  });

  const prisonerTurns = useMemo(
    () => groupEventsByBatch(eventsForActor(events, "prisoner")),
    [events],
  );
  const wardenTurns = useMemo(
    () => groupEventsByBatch(eventsForActor(events, "warden")),
    [events],
  );

  // Both sides land in one map keyed by the `user` each entry describes, so a
  // card can never end up showing the other side's numbers.
  const sides = useMemo(() => indexSides(entries), [entries]);

  const forkable = canFork(match.status);

  // Both agents' recorded turns, for the heading above the two panels. Each
  // panel groups its own side's events, so the two lengths add up.
  const turnCount = prisonerTurns.length + wardenTurns.length;

  return (
    <main>
      <MatchMasthead
        eyebrow={`Recorded match / ${match.id.slice(0, 8)}`}
        title={
          overview?.match.challenge_name ??
          match.challenge_name ??
          "Match details"
        }
        status={
          <Link
            to="/matches"
            aria-label="Close match details"
            className="match-close"
          >
            <X className="size-4" />
          </Link>
        }
        metrics={[
          { label: "Outcome", value: <OutcomeBadge match={match} /> },
          {
            label: "Duration",
            value: formatDuration(match.duration_seconds),
            signal: true,
          },
          {
            label: "Started",
            value: formatDateTime(match.started_at ?? match.created_at),
          },
          { label: "Match ID", value: match.id },
        ]}
        error={
          summaryQuery.isError ? (
            <p className="match-error">
              Failed to load match stats:{" "}
              {(summaryQuery.error as Error).message}
            </p>
          ) : undefined
        }
      />

      {overview !== null && (
        <section className="challenge-detail-band">
          <div className="page-wrap">
            <Field label="DESCRIPTION">
              <p className="text-muted-foreground">
                {overview.match.challenge_description ?? "—"}
              </p>
            </Field>
            <Field label="WIN_CONDITION">
              <p>{overview.match.win_condition}</p>
            </Field>
          </div>
        </section>
      )}

      {summaryQuery.isPending && (
        <p className="loading-line page-wrap py-10">
          Counting what each side spent...
        </p>
      )}

      {overview !== null && (
        <MatchStats
          matchId={match.id}
          match={overview.match}
          sides={sides}
          triggeredTrapTools={overview.triggered_trap_tools}
        />
      )}

      {eventsQuery.isPending && (
        <p className="loading-line page-wrap py-10">Loading match events...</p>
      )}

      {eventsQuery.isError && (
        <p className="error-line page-wrap py-10">
          Failed to load events: {(eventsQuery.error as Error).message}
        </p>
      )}

      {!eventsQuery.isPending && !eventsQuery.isError && (
        <section className="page-wrap event-section">
          <div className="agent-heading">
            <h2>Moves</h2>
            <span className="mono-label">
              {turnCount} {turnCount === 1 ? "turn" : "turns"} recorded
            </span>
          </div>

          <div className="event-grid">
            <EventBox
              title="PRISONER_AGENT"
              role="Attacker role"
              tone="prisoner"
              model={formatModel(match.prisoner_provider, match.prisoner_model)}
              turns={prisonerTurns}
              forkable={forkable}
              selectedKey={forkTarget?.key ?? null}
              forking={fork.isPending}
              onFork={(group) => {
                fork.reset();
                setForkTarget(group);
              }}
            />
            <EventBox
              title="WARDEN_AGENT"
              role="Defender role"
              tone="warden"
              model={formatModel(match.warden_provider, match.warden_model)}
              turns={wardenTurns}
              forkable={forkable}
              selectedKey={forkTarget?.key ?? null}
              forking={fork.isPending}
              onFork={(group) => {
                fork.reset();
                setForkTarget(group);
              }}
            />
          </div>
        </section>
      )}

      {forkTarget !== null && (
        <Suspense fallback={null}>
          <ForkDialog
            open
            parentMatchId={match.id}
            group={forkTarget}
            pending={fork.isPending}
            error={fork.error instanceof Error ? fork.error.message : null}
            onOpenChange={(open) => {
              if (!open && !fork.isPending) setForkTarget(null);
            }}
            onConfirm={() => {
              if (forkTarget !== null) fork.mutate(forkTarget.forkEventId);
            }}
          />
        </Suspense>
      )}
    </main>
  );
}

function EventBox({
  title,
  role,
  tone,
  model,
  turns,
  forkable,
  selectedKey,
  forking,
  onFork,
}: {
  title: string;
  role: string;
  tone: "prisoner" | "warden";
  model: string;
  turns: EventTurn[];
  forkable: boolean;
  /** Group key currently open in the fork dialog, highlighted in full. */
  selectedKey: string | null;
  forking: boolean;
  onFork: (group: EventTurn) => void;
}) {
  return (
    <section className={`event-panel ${tone}`}>
      <header className="event-panel-header">
        <span className="event-panel-name">{title}</span>
        {model !== "" && <span className="event-panel-model">{model}</span>}
        <span className="event-panel-role">{role}</span>
      </header>
      <div className="event-stream event-scroll">
        {turns.length === 0 ? (
          <p className="event-empty">No events recorded for this match.</p>
        ) : (
          turns.map((group) => (
            <EventGroup
              key={group.key}
              group={group}
              describe={describePersistedEvent}
              forkable={forkable}
              forkBlockedReason="Forking unlocks once the match has settled."
              selected={group.key === selectedKey}
              forking={forking}
              onFork={onFork}
            />
          ))
        )}
      </div>
    </section>
  );
}

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

/**
 * Index the summary entries by the side each one describes.
 *
 * The list is ordered Prisoner first, but keying off each entry's own `user`
 * means the cards stay correct whatever order they arrive in, and a side the
 * backend did not summarise is simply absent rather than mislabelled.
 */
function indexSides(
  entries: MatchSummaryResponse[],
): Record<string, MatchSummaryResponse | undefined> {
  if (entries.length === 0) return NO_SIDES;
  const sides: Record<string, MatchSummaryResponse | undefined> = {};
  for (const entry of entries) sides[entry.user] = entry;
  return sides;
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
