import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  ArrowLeft,
  Bug,
  ChevronRight,
  MessageSquareQuote,
  PenLine,
  Sparkles,
  Terminal,
  Wrench,
} from "lucide-react";
import { useMemo, useState } from "react";

import { Eyebrow } from "@/components/arbiter/app-shell";
import { OutcomeBadge } from "@/components/arbiter/outcome-badge";
import { ReviewRun } from "@/components/arbiter/review-run";
import {
  getStrategy,
  listAllConversation,
  listAllReviewEvents,
  listAllThoughts,
  listAllToolCalls,
  listAllTraps,
  getMatchSummary,
} from "@/lib/api";
import type {
  ConversationEntry,
  MatchSummaryResponse,
  MatchSide,
  ReviewMatchEvent,
  SideStats,
  ThoughtRecord,
  ToolCallRecord,
  TrapEvent,
} from "@/lib/dto";
import { formatArguments, formatDateTime, formatModel } from "@/lib/format";

/**
 * One strategy, one match, one side: everything the agent did, then what to do
 * about it.
 *
 * The scope is deliberately narrow — only the side this strategy was, only this
 * one match. A review asks "what would have played better here", and the
 * opponent's transcript is neither that question nor this strategy's business.
 * So the page reads the reviewer's per-side listings rather than the match's
 * combined transcript: its stats, its conversation, its tool calls, its
 * narration, and the raw events behind them.
 *
 * At the bottom, `ReviewRun` runs the reviewer agent over what is on screen and
 * proposes a replacement strategy. The proposal is never saved here.
 */
export function ReviewWorkbench({
  strategyId,
  matchId,
}: {
  strategyId: string;
  matchId: string;
}) {
  // The strategy names the side, so the whole page can be scoped without the
  // caller having to repeat it.
  const strategyQuery = useQuery({
    queryKey: ["strategy", strategyId],
    queryFn: () => getStrategy({ strategyId }),
  });

  const strategy = strategyQuery.data?.strategy ?? null;
  const side: MatchSide | null =
    strategy?.user === "warden" || strategy?.user === "prisoner"
      ? strategy.user
      : null;

  const summaryQuery = useQuery({
    queryKey: ["match-summary", matchId, side],
    queryFn: () => getMatchSummary(matchId),
    enabled: side !== null,
  });

  const conversationQuery = useQuery({
    queryKey: ["review-conversation", matchId, side],
    queryFn: () => listAllConversation(matchId, side ?? "prisoner"),
    enabled: side !== null,
  });

  const toolCallsQuery = useQuery({
    queryKey: ["review-tool-calls", matchId, side],
    queryFn: () => listAllToolCalls(matchId, side ?? "prisoner"),
    enabled: side !== null,
  });

  const thoughtsQuery = useQuery({
    queryKey: ["review-thoughts", matchId, side],
    queryFn: () => listAllThoughts(matchId, side ?? "prisoner"),
    enabled: side !== null,
  });

  // Traps are match-wide: a firing is one event both sides appear in.
  const trapsQuery = useQuery({
    queryKey: ["review-traps", matchId],
    queryFn: () => listAllTraps(matchId),
  });

  const eventsQuery = useQuery({
    queryKey: ["review-events", matchId, side],
    queryFn: () => listAllReviewEvents(matchId, side ?? "prisoner"),
    enabled: side !== null,
  });

  // The summary answers with one entry per side; take this strategy's own
  // rather than the Prisoner-first one, so a Warden's review shows the Warden.
  const summary: MatchSummaryResponse | null =
    (summaryQuery.data ?? []).find((entry) => entry.user === side) ?? null;
  const stats = summary?.stats ?? null;
  const isWarden = side === "warden";

  const toolBreakdown = useMemo(() => {
    const counts = stats?.tool_calls_by_name ?? {};
    return Object.entries(counts).sort(([, a], [, b]) => b - a);
  }, [stats]);

  if (strategyQuery.isPending) {
    return (
      <Frame eyebrow={`Review / ${strategyId.slice(0, 8)}`} title="Loading.">
        <p className="loading-line">Reading the strategy...</p>
      </Frame>
    );
  }

  if (strategy === null || side === null) {
    return (
      <Frame
        eyebrow={`Review / ${strategyId.slice(0, 8)}`}
        title="Unavailable."
      >
        <p className="error-line">
          {strategyQuery.error instanceof Error
            ? strategyQuery.error.message
            : strategyQuery.data === undefined
              ? "This strategy could not be found."
              : "This strategy names no side, so there is nothing to review."}
        </p>
        <BackLink />
      </Frame>
    );
  }

  const match = summary?.match ?? null;

  return (
    <Frame
      eyebrow={`Review / ${isWarden ? "warden" : "prisoner"} / ${strategyId.slice(0, 8)}`}
      title="What this agent actually did."
      tag={isWarden ? "warden" : "prisoner"}
    >
      <div className="review-context">
        <div className="review-context-strategy">
          <span className="mono-label">Strategy under review</span>
          <p>{strategy.strategy}</p>
        </div>
        <div className="review-context-match">
          <span className="mono-label">Match</span>
          <p>
            {match?.challenge_name ?? "Loading..."} ·{" "}
            {formatModel("", match?.prisoner_model ?? "")}{" "}
            <span className="text-muted">vs</span>{" "}
            {formatModel("", match?.warden_model ?? "")}
          </p>
          {match !== null && (
            <p className="review-context-outcome">
              <OutcomeBadge
                match={{ winner: match.winner, status: match.status }}
              />
              <span>
                {formatDateTime(match.finished_at ?? match.created_at)}
              </span>
            </p>
          )}
        </div>
      </div>

      <ReviewSection
        icon={<Wrench className="size-4" />}
        heading="Stats"
        note={stats === null ? "" : `${toolBreakdown.length} tools used`}
        collapsible={false}
      >
        {stats === null ? (
          <p className="empty-state">Loading this side's totals...</p>
        ) : (
          <div className="stats-cards review-stats">
            <article className={`stats-card ${side}`}>
              <header className="stats-card-header">
                <span className="stats-card-name">
                  {isWarden ? "WARDEN" : "PRISONER"}
                </span>
                <span className="stats-card-model">
                  {formatModel(
                    isWarden
                      ? (match?.warden_provider ?? "")
                      : (match?.prisoner_provider ?? ""),
                    isWarden
                      ? (match?.warden_model ?? "")
                      : (match?.prisoner_model ?? ""),
                  )}
                </span>
              </header>
              <dl className="stats-rows">
                <Stat
                  label="Tool calls"
                  value={stats.tool_calls ?? toolCallTotal(stats)}
                  signal
                />
                <Stat label="Succeeded" value={stats.successful_tool_calls} />
                <Stat label="Failed" value={stats.failed_tool_calls} />
                <Stat label="Refused" value={stats.rejected_tool_calls} />
                <Stat
                  label={isWarden ? "Traps armed" : "Times trapped"}
                  value={
                    isWarden
                      ? (stats.traps_armed ?? 0)
                      : (stats.times_trapped ?? 0)
                  }
                />
                {isWarden && (
                  <Stat
                    label="Traps triggered"
                    value={stats.traps_triggered ?? 0}
                  />
                )}
                <Stat
                  label="Credits left"
                  value={stats.credits_remaining ?? "—"}
                />
              </dl>
              {toolBreakdown.length > 0 && (
                <div className="stats-tools">
                  <span className="mono-label">Tools used</span>
                  <div className="stats-chips">
                    {toolBreakdown.map(([tool, count]) => (
                      <span className="stats-chip" key={tool}>
                        {tool}
                        <span className="stats-chip-count">{count}</span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </article>
          </div>
        )}
      </ReviewSection>
      {/*
       * The analysis brief sits directly under the stats: it is the next
       * thing to do with what was just read, not another listing of the
       * match.
       */}
      <ReviewRun
        strategyId={strategyId}
        matchId={matchId}
        side={side}
        challengerName={formatModel(
          isWarden
            ? (match?.warden_provider ?? "")
            : (match?.prisoner_provider ?? ""),
          isWarden
            ? (match?.warden_model ?? "")
            : (match?.prisoner_model ?? ""),
        )}
        handoff={{
          challengeId: match?.challenge_id ?? "",
          prisonerProvider: match?.prisoner_provider ?? "",
          prisonerModel: match?.prisoner_model ?? "",
          wardenProvider: match?.warden_provider ?? "",
          wardenModel: match?.warden_model ?? "",
        }}
      />

      <ConversationPanel
        entries={conversationQuery.data}
        loading={conversationQuery.isPending}
      />

      <ToolCallsPanel
        calls={toolCallsQuery.data}
        loading={toolCallsQuery.isPending}
      />

      <ThoughtsPanel
        thoughts={thoughtsQuery.data}
        loading={thoughtsQuery.isPending}
      />

      <TrapsPanel traps={trapsQuery.data} loading={trapsQuery.isPending} />

      <EventsPanel events={eventsQuery.data} loading={eventsQuery.isPending} />
    </Frame>
  );
}

/**
 * The page's frame: a compact header with the way back, then whatever is inside.
 *
 * The side tag carries the side's own accent, so a Prisoner's review and a
 * Warden's stay distinguishable.
 */
function Frame({
  eyebrow,
  title,
  tag,
  children,
}: {
  eyebrow: string;
  title: string;
  tag?: MatchSide;
  children: React.ReactNode;
}) {
  return (
    <main className="page-wrap page-pad">
      <header className="strategy-header">
        <div className="strategy-header-id">
          <BackLink />
          <span className="mono-label">{eyebrow}</span>
          {tag !== undefined && (
            <span className={`strategy-side-tag is-${tag}`}>
              {tag === "warden" ? "Warden" : "Prisoner"}
            </span>
          )}
        </div>
      </header>

      <h1 className="review-title">{title}</h1>

      {children}
    </main>
  );
}

function BackLink() {
  return (
    <Link to="/strategy" className="strategy-back" search={{}}>
      <ArrowLeft className="size-3.5" />
      Strategy
    </Link>
  );
}

/** One section of the review: a heading and whatever is under it. */
/**
 * One section of the review: a heading that folds its contents away.
 *
 * Everything but the stats card folds, because the record is long and a reader
 * usually wants one part of it at a time. Sections start open so the page still
 * reads end to end; the toggle is for cutting it down. The stats section passes
 * `collapsible={false}` and keeps its plain heading.
 */
function ReviewSection({
  icon,
  heading,
  note,
  collapsible = true,
  children,
}: {
  icon: React.ReactNode;
  heading: string;
  note?: string;
  collapsible?: boolean;
  children: React.ReactNode;
}) {
  // Folded to start. The stats card above is the page's summary; the listings
  // below it are long, and a reader opens the one they are looking for.
  const [open, setOpen] = useState(false);

  return (
    <section className="archive-section">
      <div className="agent-heading">
        <h2>
          {collapsible ? (
            <button
              type="button"
              className="section-toggle"
              aria-expanded={open}
              onClick={() => setOpen((current) => !current)}
            >
              {icon}
              {heading}
              <ChevronRight
                className="section-chevron size-4"
                aria-hidden="true"
              />
            </button>
          ) : (
            <>
              {icon}
              {heading}
            </>
          )}
        </h2>
        {note !== undefined && note !== "" && (
          <span className="mono-label">{note}</span>
        )}
      </div>
      {(!collapsible || open) && children}
    </section>
  );
}

function Stat({
  label,
  value,
  signal,
}: {
  label: string;
  value: number | string;
  signal?: boolean;
}) {
  return (
    <div className="stats-row">
      <dt>{label}</dt>
      <dd className={signal === true ? "is-signal" : undefined}>{value}</dd>
    </div>
  );
}

/** The stored conversation, one row per step. */
function ConversationPanel({
  entries,
  loading,
}: {
  entries: ConversationEntry[] | undefined;
  loading: boolean;
}) {
  const rows = entries ?? [];
  return (
    <ReviewSection
      icon={<MessageSquareQuote className="size-4" />}
      heading="Conversation"
      note={loading ? "Loading..." : `${rows.length} steps`}
    >
      {rows.length === 0 ? (
        <p className="empty-state">
          {loading
            ? "Loading the conversation..."
            : "No conversation was stored for this agent in this match."}
        </p>
      ) : (
        <div className="review-stream">
          {rows.map((entry) => (
            <ConversationRow entry={entry} key={entry.index} />
          ))}
        </div>
      )}
    </ReviewSection>
  );
}

/**
 * One conversation step.
 *
 * A tool return carries whatever the sandbox gave back — often kilobytes of
 * output for a call whose arguments already say what was asked. That payload is
 * folded behind `[show output]` so the exchange reads as a sequence of moves
 * rather than a wall of stdout; the arguments of a call stay open, since the
 * move is the point.
 */
function ConversationRow({ entry }: { entry: ConversationEntry }) {
  const [showOutput, setShowOutput] = useState(false);

  const isReturn = entry.kind === "tool-return";
  const payload = formatArguments(entry.content);
  const hasHiddenOutput = isReturn && payload !== "";

  if (entry.text !== null && entry.text !== "") {
    return (
      <div className={`review-line is-${entry.kind}`}>
        <span className="review-line-index">{entry.index}</span>
        <span className="review-line-kind">{conversationKind(entry)}</span>
        <span className="review-line-text">{entry.text}</span>
      </div>
    );
  }

  return (
    <div className={`review-line is-${entry.kind}`}>
      <span className="review-line-index">{entry.index}</span>
      <span className="review-line-kind">{conversationKind(entry)}</span>
      <span className="review-line-text">
        <span className="review-line-payload">
          {entry.tool_name !== null && (
            <strong className="review-tool">{entry.tool_name}</strong>
          )}
          {isReturn ? "Output returned." : payload}
        </span>
        {hasHiddenOutput && !showOutput && (
          <button
            type="button"
            className="review-show-output"
            onClick={() => setShowOutput(true)}
            aria-expanded={false}
          >
            [show output]
          </button>
        )}
        {hasHiddenOutput && showOutput && (
          <>
            <button
              type="button"
              className="review-show-output"
              onClick={() => setShowOutput(false)}
              aria-expanded={true}
            >
              [hide output]
            </button>
            <span className="review-output">{payload}</span>
          </>
        )}
      </span>
    </div>
  );
}

/** What a conversation step was, in the app's vocabulary. */
function conversationKind(entry: ConversationEntry): string {
  switch (entry.kind) {
    case "user-prompt":
      return "PROMPT";
    case "tool-call":
      return "CALL";
    case "tool-return":
      return "RETURN";
    case "text":
      return "SAID";
    default:
      return entry.kind.toUpperCase();
  }
}

/** Every tool call, with its outcome. */
function ToolCallsPanel({
  calls,
  loading,
}: {
  calls: ToolCallRecord[] | undefined;
  loading: boolean;
}) {
  const rows = calls ?? [];
  return (
    <ReviewSection
      icon={<Terminal className="size-4" />}
      heading="Tool calls"
      note={loading ? "Loading..." : `${rows.length} calls`}
    >
      {rows.length === 0 ? (
        <p className="empty-state">
          {loading
            ? "Loading tool calls..."
            : "This agent made no tool calls in this match."}
        </p>
      ) : (
        <div className="review-stream">
          {rows.map((call) => (
            <div
              className={`review-line ${call.success === false ? "is-failed" : "is-ok"}`}
              key={call.event_id}
            >
              <span className="review-line-index">
                {formatDateTime(call.timestamp).split(", ").pop()}
              </span>
              <span className="review-line-kind">{call.tool ?? "unknown"}</span>
              <span className="review-line-text">
                {formatArguments(call.arguments)}
                {call.error !== null && (
                  <span className="review-line-error">{call.error}</span>
                )}
              </span>
            </div>
          ))}
        </div>
      )}
    </ReviewSection>
  );
}

/** The narration the agent reported for the log. */
function ThoughtsPanel({
  thoughts,
  loading,
}: {
  thoughts: ThoughtRecord[] | undefined;
  loading: boolean;
}) {
  const rows = thoughts ?? [];
  return (
    <ReviewSection
      icon={<PenLine className="size-4" />}
      heading="Thoughts"
      note={loading ? "Loading..." : `${rows.length} reported`}
    >
      {rows.length === 0 ? (
        <p className="empty-state">
          {loading
            ? "Loading narration..."
            : "This agent reported no narration for the log."}
        </p>
      ) : (
        <div className="review-stream">
          {rows.map((thought) => (
            <div className="review-line is-text" key={thought.event_id}>
              <span className="review-line-index">
                {formatDateTime(thought.timestamp).split(", ").pop()}
              </span>
              <span className="review-line-kind">SAID</span>
              <span className="review-line-text">{thought.content}</span>
            </div>
          ))}
        </div>
      )}
    </ReviewSection>
  );
}

/** Trap firings, which are match-wide rather than one side's. */
function TrapsPanel({
  traps,
  loading,
}: {
  traps: TrapEvent[] | undefined;
  loading: boolean;
}) {
  const rows = traps ?? [];
  return (
    <ReviewSection
      icon={<Bug className="size-4" />}
      heading="Traps"
      note={loading ? "Loading..." : `${rows.length} fired`}
    >
      {rows.length === 0 ? (
        <p className="empty-state">
          {loading ? "Loading traps..." : "No traps fired in this match."}
        </p>
      ) : (
        <div className="review-stream">
          {rows.map((trap) => (
            <div className="review-line is-system" key={trap.event_id}>
              <span className="review-line-index">
                {formatDateTime(trap.timestamp).split(", ").pop()}
              </span>
              <span className="review-line-kind">{trap.trap ?? "trap"}</span>
              <span className="review-line-text">
                watching {trap.target ?? "—"} · prisoner turn{" "}
                {trap.prisoner_turn ?? "?"} · warden turn{" "}
                {trap.warden_turn ?? "?"}
              </span>
            </div>
          ))}
        </div>
      )}
    </ReviewSection>
  );
}

/** The raw events behind the shaped listings. */
function EventsPanel({
  events,
  loading,
}: {
  events: ReviewMatchEvent[] | undefined;
  loading: boolean;
}) {
  const rows = events ?? [];
  return (
    <ReviewSection
      icon={<Sparkles className="size-4" />}
      heading="Raw events"
      note={loading ? "Loading..." : `${rows.length} recorded`}
    >
      {rows.length === 0 ? (
        <p className="empty-state">
          {loading ? "Loading events..." : "No raw events for this side."}
        </p>
      ) : (
        <div className="review-stream is-compact">
          {rows.map((event) => (
            <div className="review-line is-system" key={event.event_id}>
              <span className="review-line-index">
                {formatDateTime(event.timestamp).split(", ").pop()}
              </span>
              <span className="review-line-kind">{event.event_type}</span>
              <span className="review-line-text">
                {formatArguments(event.action)}
              </span>
            </div>
          ))}
        </div>
      )}
    </ReviewSection>
  );
}

/** The Engine's own total, or the three counted outcomes added up. */
function toolCallTotal(stats: SideStats): number {
  return (
    stats.successful_tool_calls +
    stats.failed_tool_calls +
    stats.rejected_tool_calls
  );
}
