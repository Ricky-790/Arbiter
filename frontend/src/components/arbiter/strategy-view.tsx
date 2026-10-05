import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, ArrowUpRight, ScanSearch } from "lucide-react";

import { Eyebrow } from "@/components/arbiter/app-shell";
import { OutcomeBadge } from "@/components/arbiter/outcome-badge";
import { getStrategy } from "@/lib/api";
import type { MatchSide, StrategyMatchSummary } from "@/lib/dto";
import { formatDateTime, formatModel } from "@/lib/format";

/**
 * One saved strategy: its wording, and the matches that have run it.
 *
 * The page is deliberately quiet about the strategy itself — the wording is one
 * short card at the top — because the interesting part is the lineage. A
 * strategy is promoted out of a run and then reused, so the question it answers
 * is whether the wording works: where it came from, and which matches have been
 * started with it since. The origin is listed apart from the uses, since it ran
 * the wording before the strategy existed.
 */
export function StrategyView({ strategyId }: { strategyId: string }) {
  const strategyQuery = useQuery({
    queryKey: ["strategy", strategyId],
    queryFn: () => getStrategy({ strategyId }),
  });

  if (strategyQuery.isPending) {
    return (
      <main className="page-wrap page-pad">
        <Header side={null} id={strategyId} />
        <p className="loading-line">Reading the library entry...</p>
      </main>
    );
  }

  if (strategyQuery.isError || strategyQuery.data === undefined) {
    return (
      <main className="page-wrap page-pad">
        <Header side={null} id={strategyId} />
        <p className="error-line">
          {strategyQuery.error instanceof Error
            ? strategyQuery.error.message
            : "This strategy could not be found."}
        </p>
      </main>
    );
  }

  const {
    strategy,
    parent_match: parent,
    used_in_matches: used,
  } = strategyQuery.data;
  // The column is a plain string on the backend, so narrow it here: anything
  // else is not a side this page knows how to colour or name.
  const side: MatchSide | null =
    strategy.user === "warden" || strategy.user === "prisoner"
      ? strategy.user
      : null;

  return (
    <main className="page-wrap page-pad">
      <Header side={side} id={strategy.id} />

      <article className="strategy-card">
        <div className="strategy-card-head">
          <Eyebrow>The strategy</Eyebrow>
          <span className="mono-label">
            Saved {formatDateTime(strategy.created_at)}
          </span>
        </div>
        <p className="strategy-card-text">{strategy.strategy}</p>
      </article>

      <section className="archive-section">
        <div className="agent-heading">
          <h2>Promoted from</h2>
          <span className="mono-label">Where the wording was first played</span>
        </div>
        {parent === null ? (
          <p className="empty-state mt-6">
            The match it came from is no longer available.
          </p>
        ) : (
          <LineageRow match={parent} role="origin" strategyId={strategy.id} />
        )}
      </section>

      <section className="archive-section">
        <div className="agent-heading">
          <h2>Used in</h2>
          <span className="mono-label">
            {used.total === 0
              ? "Not used yet"
              : `${used.total} ${used.total === 1 ? "match" : "matches"} started from it`}
          </span>
        </div>
        {used.items.length === 0 ? (
          <p className="empty-state mt-6">
            Nothing has been started from this strategy yet. Pick it when
            launching a match to put the wording to work.
          </p>
        ) : (
          used.items.map((match) => (
            <LineageRow
              key={match.match_id}
              match={match}
              role="use"
              strategyId={strategy.id}
            />
          ))
        )}
      </section>
    </main>
  );
}

/**
 * The page's only heading: which strategy this is, which side it is for, and the
 * way back.
 *
 * The label is the side's own colour, so the Prisoner's and the Warden's
 * strategies stay distinguishable at a glance, as on the stats card.
 */
function Header({
  side,
  id,
}: {
  /** Null while the entry is loading, unreadable, or not a known side. */
  side: MatchSide | null;
  id: string;
}) {
  return (
    <header className="strategy-header">
      <div className="strategy-header-id">
        <Link to="/archive" className="strategy-back">
          <ArrowLeft className="size-3.5" />
          Archive
        </Link>
        <span className="mono-label">
          Strategy / {side ?? "—"} / {id.slice(0, 8)}
        </span>
        {side !== null && (
          <span className={`strategy-side-tag is-${side}`}>
            {side === "warden" ? "Warden" : "Prisoner"}
          </span>
        )}
      </div>
    </header>
  );
}

/**
 * One match in a strategy's lineage: its record on the left, the review action
 * on the right.
 *
 * The origin row is captioned, because the parent is not a use of the strategy:
 * it ran the wording before the entry existed. Both rows can be reviewed — the
 * question is the same either way, what would have played better here.
 */
function LineageRow({
  match,
  role,
  strategyId,
}: {
  match: StrategyMatchSummary;
  role: "origin" | "use";
  strategyId: string;
}) {
  return (
    <div className={`lineage-row is-${role}`}>
      <Link
        to="/matches"
        search={{ match_id: match.match_id }}
        className="lineage-row-link"
      >
        <span className="lineage-row-challenge">
          {match.challenge_name ?? "Unknown challenge"}
        </span>
        <span className="lineage-row-models">
          {formatModel("", match.prisoner_model)}{" "}
          <span className="text-muted">vs</span>{" "}
          {formatModel("", match.warden_model)}
        </span>
        <span className="lineage-row-outcome">
          <OutcomeBadge
            match={{ winner: match.winner, status: match.winner ?? "unknown" }}
          />
        </span>
        <span className="lineage-row-caption">
          {role === "origin" ? (
            "Promoted from this match"
          ) : (
            <span className="lineage-row-id">{match.match_id}</span>
          )}
        </span>
        <ArrowUpRight className="lineage-row-arrow size-4" />
      </Link>

      <Link
        to="/review"
        search={{ strategy_id: strategyId, match_id: match.match_id }}
        className="lineage-review"
      >
        <ScanSearch className="size-3.5" />
        Review
      </Link>
    </div>
  );
}
