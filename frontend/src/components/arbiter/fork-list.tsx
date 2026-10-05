import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ArrowUpRight, ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import { listForks } from "@/lib/api";
import type { ForkSchema } from "@/lib/dto";
import { formatDateTime } from "@/lib/format";
import { isForkPending } from "@/lib/match-status";

const PAGE_SIZE = 20;

/**
 * Every saved fork point, newest first — the archive's second section.
 *
 * A fork is a checkpoint on a finished match, not a match of its own, so this
 * list is about where the work is: what point it was taken at, which match it
 * came from, and whether its snapshot has finished rebuilding.
 */
export function ForkList() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);

  const forksQuery = useQuery({
    queryKey: ["forks", page],
    queryFn: () => listForks({ page, pageSize: PAGE_SIZE }),
    // A pending fork is being rebuilt in the background with no progress
    // signal, so the list rechecks while any row is still working.
    refetchInterval: (query) =>
      (query.state.data?.items ?? []).some((fork) => isForkPending(fork.status))
        ? 2500
        : false,
  });

  const forks = forksQuery.data?.items ?? [];
  const pages = forksQuery.data?.pages ?? 0;
  const total = forksQuery.data?.total ?? 0;
  const pending = forks.filter((fork) => isForkPending(fork.status)).length;

  const openFork = (fork: ForkSchema) => {
    navigate({ to: "/archive", search: { fork_id: fork.id } });
  };

  return (
    <section className="archive-section">
      <div className="agent-heading">
        <h2>Forks</h2>
        <span className="mono-label">
          {total === 0
            ? "None saved yet"
            : `${total} saved · ${pending === 0 ? "all ready" : `${pending} rebuilding`}`}
        </span>
      </div>

      {forksQuery.isPending && (
        <p className="loading-line mt-6">Loading saved forks...</p>
      )}

      {forksQuery.isError && (
        <p className="error-line mt-6">
          Failed to load forks: {(forksQuery.error as Error).message}
        </p>
      )}

      {!forksQuery.isPending && !forksQuery.isError && (
        <>
          <div className="fork-list mt-6">
            {forks.length === 0 ? (
              <p className="empty-state">
                No fork points yet. Open a finished match and save one from any
                turn.
              </p>
            ) : (
              forks.map((fork, index) => (
                <button
                  type="button"
                  key={fork.id}
                  className="fork-row"
                  onClick={() => openFork(fork)}
                >
                  <span className="fork-row-index">
                    {(index + 1).toString().padStart(2, "0")}
                  </span>
                  <span className="fork-row-point">
                    <span className="fork-row-label">Captured at</span>
                    <span className="fork-row-time">
                      {formatDateTime(fork.branch_event_timestamp)}
                    </span>
                  </span>
                  <span className="fork-row-parent">
                    <span className="fork-row-label">From match</span>
                    <span className="fork-row-id">{fork.parent_match_id}</span>
                  </span>
                  <span className="fork-row-saved">
                    <span className="fork-row-label">Saved</span>
                    <span className="fork-row-id">
                      {formatDateTime(fork.created_at)}
                    </span>
                  </span>
                  <ForkStatusBadge status={fork.status} />
                  <ArrowUpRight className="fork-row-arrow size-4" />
                </button>
              ))
            )}
          </div>

          {total > PAGE_SIZE && (
            <div className="pagination">
              <button
                type="button"
                className="button-secondary"
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                disabled={page <= 1}
              >
                <ChevronLeft className="size-3" />
                Prev
              </button>
              <span className="pagination-count">
                Page {pages === 0 ? 0 : page} / {pages}
              </span>
              <button
                type="button"
                className="button-secondary"
                onClick={() => setPage((current) => current + 1)}
                disabled={page >= pages}
              >
                Next
                <ChevronRight className="size-3" />
              </button>
              <span className="pagination-count pagination-total">
                {total} forks
              </span>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function ForkStatusBadge({ status }: { status: string }) {
  const label =
    status === "ready"
      ? "Ready"
      : status === "pending"
        ? "Rebuilding"
        : status === "failed"
          ? "Failed"
          : status;
  return (
    <span className={`fork-status is-${status}`}>
      <span className="fork-status-dot" aria-hidden="true" />
      {label}
    </span>
  );
}
