import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ArrowUpRight, ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import { listStrategies } from "@/lib/api";
import type { StrategySchema } from "@/lib/dto";
import { formatDateTime } from "@/lib/format";

const PAGE_SIZE = 20;

/**
 * The strategy library, newest first.
 *
 * A strategy is one side's approach, promoted out of a finished match, ready to
 * start a later one. This lists the wording as it is stored — the label the
 * library files it under, which the backend derives from that wording — and the
 * match it came from; the full text and the lineage live one click away.
 *
 * Paged, because the library grows for as long as matches are run.
 */
export function StrategyList() {
  const navigate = useNavigate();
  const [page, setPage] = useState(0);

  const strategiesQuery = useQuery({
    queryKey: ["strategies", page],
    queryFn: () =>
      listStrategies({ offset: page * PAGE_SIZE, limit: PAGE_SIZE }),
  });

  const strategies = strategiesQuery.data?.items ?? [];
  const total = strategiesQuery.data?.total ?? 0;
  const hasMore = strategiesQuery.data?.has_more ?? false;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <section className="archive-section">
      <div className="agent-heading">
        <h2>Strategies</h2>
        <span className="mono-label">
          {total === 0
            ? "None saved yet"
            : `${total} saved · promoted from finished matches`}
        </span>
      </div>

      {strategiesQuery.isPending && (
        <p className="loading-line mt-6">Loading the strategy library...</p>
      )}

      {strategiesQuery.isError && (
        <p className="error-line mt-6">
          Failed to load strategies: {(strategiesQuery.error as Error).message}
        </p>
      )}

      {!strategiesQuery.isPending && !strategiesQuery.isError && (
        <>
          <div className="strategy-list">
            {strategies.length === 0 ? (
              <p className="empty-state">
                No strategies saved yet. Open a finished match that ran with one
                and promote it from the stats card.
              </p>
            ) : (
              strategies.map((strategy, index) => (
                <StrategyRow
                  key={strategy.id}
                  strategy={strategy}
                  index={page * PAGE_SIZE + index + 1}
                  onOpen={() =>
                    navigate({
                      to: "/strategy",
                      search: { strategy_id: strategy.id },
                    })
                  }
                />
              ))
            )}
          </div>

          {total > PAGE_SIZE && (
            <div className="pagination">
              <button
                type="button"
                className="button-secondary"
                onClick={() => setPage((current) => Math.max(0, current - 1))}
                disabled={page <= 0}
              >
                <ChevronLeft className="size-3" />
                Prev
              </button>
              <span className="pagination-count">
                Page {page + 1} / {pages}
              </span>
              <button
                type="button"
                className="button-secondary"
                onClick={() => setPage((current) => current + 1)}
                disabled={!hasMore}
              >
                Next
                <ChevronRight className="size-3" />
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

/**
 * One saved strategy as a row.
 *
 * Shaped like the fork rows below it — index, subject, text, origin, date — so
 * the two sections of the archive read as one list of records.
 */
function StrategyRow({
  strategy,
  index,
  onOpen,
}: {
  strategy: StrategySchema;
  /** 1-based position across the whole library, not just this page. */
  index: number;
  onOpen: () => void;
}) {
  return (
    <button type="button" className="strategy-row" onClick={onOpen}>
      <span className="strategy-row-index">
        {index.toString().padStart(2, "0")}
      </span>
      <span className={`strategy-row-side is-${strategy.user}`}>
        {strategy.user === "warden" ? "Warden" : "Prisoner"}
      </span>
      <span className="strategy-row-text">
        {strategy.one_line_description === ""
          ? "(no description)"
          : strategy.one_line_description}
      </span>
      <span className="strategy-row-challenge">
        <span className="strategy-row-label">Challenge</span>
        <span className="strategy-row-id">
          {strategy.challenge_name ?? "Unknown"}
        </span>
      </span>
      <span className="strategy-row-from">
        <span className="strategy-row-label">From match</span>
        <span className="strategy-row-id">{strategy.match_id}</span>
      </span>
      <span className="strategy-row-saved">
        <span className="strategy-row-label">Saved</span>
        <span className="strategy-row-id">
          {formatDateTime(strategy.created_at)}
        </span>
      </span>
      <ArrowUpRight className="strategy-row-arrow size-4" />
    </button>
  );
}
