import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BookmarkPlus, Check } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { SaveStrategyDialog } from "@/components/arbiter/save-strategy-dialog";
import { saveStrategy } from "@/lib/api";
import { formatCount, formatModel } from "@/lib/format";
import type {
  MatchOverview,
  MatchSide,
  MatchSummaryResponse,
  SideStats,
} from "@/lib/dto";

/**
 * Both sides' totals, as the reviewer counted them.
 *
 * `GET /reviewer/summary` answers with one entry per side, each scoped entirely
 * to its own stats, strategy and opening message, so this renders a card per
 * side directly above the two transcripts below it — the numbers that produced
 * those turns. Entries are keyed off their own `user` rather than their position
 * in the list, so a side can never be labelled as the other one.
 *
 * The Engine's closing summary is what fills `credits_remaining` and
 * `tool_calls`, and it is absent for matches recorded before that write, so
 * those read as a dash rather than as zero. The per-tool breakdown is counted
 * from events instead and is therefore always present.
 */
export function MatchStats({
  matchId,
  match,
  sides,
  triggeredTrapTools,
}: {
  matchId: string;
  match: MatchOverview;
  /** Each side's summary entry, keyed by the `user` it describes. */
  sides: Record<string, MatchSummaryResponse | undefined>;
  triggeredTrapTools: Record<string, number>;
}) {
  const queryClient = useQueryClient();
  const [promoting, setPromoting] = useState<MatchSide | null>(null);

  const promote = useMutation({
    mutationFn: (user: MatchSide) => saveStrategy({ match_id: matchId, user }),
    onSuccess: async (saved) => {
      // Saving writes the new id onto `matches.strategy_id`, the same match row
      // the summary reads, so refetch it: that is what locks this side's button.
      await queryClient.invalidateQueries({
        queryKey: ["match-summary", matchId],
      });
      setPromoting(null);
      toast.success(
        `${saved.user === "warden" ? "Warden" : "Prisoner"} strategy saved`,
        { description: saved.one_line_description },
      );
    },
    // The dialog stays open on failure, so the reason shows where it was asked.
    onError: (error) => {
      toast.error("Could not save the strategy", {
        description: error instanceof Error ? error.message : "Request failed",
      });
    },
  });

  return (
    <section className="stats-band">
      <div className="page-wrap">
        <div className="agent-heading">
          <h2>Stats</h2>
          <span className="mono-label">{totalToolCalls(sides)}</span>
        </div>

        <div className="stats-cards">
          <SideCard
            side="prisoner"
            entry={sides["prisoner"]}
            model={formatModel(match.prisoner_provider, match.prisoner_model)}
            savedStrategyId={match.strategy_id["prisoner"]}
            onRevise={() => {
              promote.reset();
              setPromoting("prisoner");
            }}
          />
          <SideCard
            side="warden"
            entry={sides["warden"]}
            model={formatModel(match.warden_provider, match.warden_model)}
            savedStrategyId={match.strategy_id["warden"]}
            onRevise={() => {
              promote.reset();
              setPromoting("warden");
            }}
          />
        </div>

        <TrapStrip trapTools={triggeredTrapTools} />
      </div>

      <SaveStrategyDialog
        open={promoting !== null}
        side={promoting}
        strategy={
          promoting === null ? null : (sides[promoting]?.strategy ?? null)
        }
        pending={promote.isPending}
        error={promote.error instanceof Error ? promote.error.message : null}
        onOpenChange={(open) => {
          if (!open && !promote.isPending) setPromoting(null);
        }}
        onConfirm={() => {
          if (promoting !== null) promote.mutate(promoting);
        }}
      />
    </section>
  );
}

/**
 * Both sides' tool calls in one number, for the heading beside the cards.
 *
 * The cards carry the per-side totals; this is only the match-wide line, so it
 * stays silent when neither side recorded any.
 */
function totalToolCalls(
  sides: Record<string, MatchSummaryResponse | undefined>,
): string {
  const total = Object.values(sides).reduce(
    (sum, entry) =>
      entry === undefined ? sum : sum + toolCallTotal(entry.stats),
    0,
  );
  if (total === 0) return "";
  return `${formatCount(total)} tool calls across both agents`;
}

/**
 * One side's card: its model, the strategy it ran, its totals, the tools it
 * reached for, and what can be done with that strategy.
 */
function SideCard({
  side,
  entry,
  model,
  savedStrategyId,
  onRevise,
}: {
  side: MatchSide;
  entry: MatchSummaryResponse | undefined;
  model: string;
  /** Set once this side's strategy has been promoted into the library. */
  savedStrategyId: string | undefined;
  onRevise: () => void;
}) {
  const label = side === "prisoner" ? "PRISONER" : "WARDEN";
  const hint = side === "prisoner" ? "Attacker" : "Defender";
  const stats = entry?.stats;
  const strategy = entry?.strategy ?? null;
  const hasStrategy = strategy !== null && strategy.trim() !== "";
  // Already in the library: the entry is fixed, so revising it is not on offer
  // yet. Kept inert rather than hidden so the card's shape stays stable.
  const saved = savedStrategyId !== undefined && savedStrategyId !== "";

  return (
    <article className={`stats-card ${side}`}>
      <header className="stats-card-header">
        <span className="stats-card-name">{label}</span>
        <span className="stats-card-model">{model}</span>
        <span className="stats-card-role">{hint}</span>
      </header>

      {stats === undefined ? (
        <p className="stats-card-empty">
          No stats recorded for this side of the match.
        </p>
      ) : (
        <>
          <Strategy strategy={strategy} />

          <dl className="stats-rows">
            <Stat
              label="Tool calls"
              value={formatCount(toolCallTotal(stats))}
              signal
            />
            <Stat
              label="Succeeded"
              value={formatCount(stats.successful_tool_calls)}
            />
            <Stat label="Failed" value={formatCount(stats.failed_tool_calls)} />
            <Stat
              label="Refused"
              value={formatCount(stats.rejected_tool_calls)}
            />
            <Stat
              label="Credits left"
              value={formatCount(stats.credits_remaining)}
            />
            {/*
              The trap counters are side-owned rather than shared: the Prisoner is
              the one that gets caught, the Warden the one that arms traps. Each
              is `null` on the other side by design, so only the owning rows show.
            */}
            {side === "prisoner" ? (
              <Stat
                label="Times trapped"
                value={formatCount(stats.times_trapped)}
              />
            ) : (
              <>
                <Stat
                  label="Traps armed"
                  value={formatCount(stats.traps_armed)}
                />
                <Stat
                  label="Traps triggered"
                  value={formatCount(stats.traps_triggered)}
                />
              </>
            )}
          </dl>

          <ToolBreakdown counts={stats.tool_calls_by_name} />

          {/*
            The one action this card offers. Locked when the match ran no
            strategy at all, since there would be nothing to promote; inert once
            the side is in the library, which is the only state it reaches after
            a successful save.
          */}
          <div className="stats-card-actions">
            <button
              type="button"
              className="stats-revise button-primary"
              onClick={onRevise}
              disabled={!hasStrategy || saved}
              title={
                saved
                  ? "Already saved to the strategy library"
                  : hasStrategy
                    ? undefined
                    : "This match ran no strategy to save"
              }
            >
              {saved ? (
                <Check className="size-3.5" />
              ) : (
                <BookmarkPlus className="size-3.5" />
              )}
              {saved ? "Saved to library" : "Revise this strategy"}
            </button>
          </div>
        </>
      )}
    </article>
  );
}

/**
 * The strategy this side ran, as the match recorded it.
 *
 * Read off `matches.strategy`, so it is what the match actually played rather
 * than a parse back out of the opening prompt. `null` for a match started
 * without one, which is the common case, so the row is left out entirely rather
 * than showing an empty block above the numbers.
 */
function Strategy({ strategy }: { strategy: string | null }) {
  if (strategy === null || strategy.trim() === "") return null;

  return (
    <div className="stats-strategy">
      <span className="mono-label">Strategy</span>
      <p>{strategy}</p>
    </div>
  );
}

/** One label/value row. */
function Stat({
  label,
  value,
  signal,
}: {
  label: string;
  value: string;
  signal?: boolean;
}) {
  return (
    <div className="stats-row">
      <dt>{label}</dt>
      <dd className={signal === true ? "is-signal" : undefined}>{value}</dd>
    </div>
  );
}

/**
 * How many tool calls a side made in total.
 *
 * The Engine's own total is preferred, but it is absent for matches recorded
 * before that column existed; the three counted outcomes add up to the same
 * number, so the card still reads correctly without it.
 */
function toolCallTotal(stats: SideStats): number {
  if (stats.tool_calls !== null) return stats.tool_calls;
  return (
    stats.successful_tool_calls +
    stats.failed_tool_calls +
    stats.rejected_tool_calls
  );
}

/** The per-tool counts, busiest first. Absent when a side called nothing. */
function ToolBreakdown({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts).sort(
    ([, left], [, right]) => right - left || 0,
  );
  if (entries.length === 0) return null;

  return (
    <div className="stats-tools">
      <span className="mono-label">Tools used</span>
      <div className="stats-chips">
        {entries.map(([tool, count]) => (
          <span className="stats-chip" key={tool}>
            {tool}
            <span className="stats-chip-count">{formatCount(count)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * Which trap tools fired, and how often.
 *
 * A firing is one event both sides appear in, so this is shared rather than
 * per-side and sits under the two cards instead of inside either of them.
 */
function TrapStrip({ trapTools }: { trapTools: Record<string, number> }) {
  const entries = Object.entries(trapTools).sort(
    ([, left], [, right]) => right - left || 0,
  );
  if (entries.length === 0) return null;

  return (
    <div className="stats-trap-strip">
      <span className="mono-label">Trap tools fired</span>
      <div className="stats-chips">
        {entries.map(([tool, count]) => (
          <span className="stats-chip" key={tool}>
            {tool}
            <span className="stats-chip-count">{formatCount(count)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
