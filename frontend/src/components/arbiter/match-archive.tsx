import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import { Eyebrow } from "@/components/arbiter/app-shell";
import { OutcomeBadge } from "@/components/arbiter/outcome-badge";
import { listMatches } from "@/lib/api";
import type { MatchListSchema, SortOrder } from "@/lib/dto";
import { formatDateTime, formatDuration, formatModel } from "@/lib/format";
import { isLiveStatus } from "@/lib/match-status";

const PAGE_SIZE = 20;

const COLUMNS = [
  "#",
  "Challenge",
  "Prisoner",
  "Warden",
  "Outcome",
  "Duration",
  "Created",
];

export function MatchArchive() {
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<SortOrder>("date_desc");

  const matchesQuery = useQuery({
    queryKey: ["matches", page, sort],
    queryFn: () => listMatches({ page, pageSize: PAGE_SIZE, sort }),
  });

  const rows = matchesQuery.data?.items ?? [];
  const pages = matchesQuery.data?.pages ?? 0;
  const total = matchesQuery.data?.total ?? 0;

  const changeSort = (next: SortOrder) => {
    setSort(next);
    setPage(1);
  };

  const openMatch = (match: MatchListSchema) => {
    // One URL for every state: `MatchView` reads the row and decides whether
    // this is a live room or a settled transcript.
    navigate({ to: "/matches", search: { match_id: match.id } });
  };

  return (
    <main className="page-wrap page-pad">
      <div className="page-intro">
        <div>
          <Eyebrow>Match archive / record room</Eyebrow>
          <h1 className="page-title">Every run leaves a trace.</h1>
          <p className="page-deck">
            Browse settled match histories and step back into live rooms where
            the agents are still moving.
          </p>
        </div>
        <div className="page-meta">
          <span>Archive index</span>
          <strong>{total.toString().padStart(2, "0")}</strong>
          <span>Records / newest first</span>
        </div>
      </div>

      <div className="archive-layout mt-8">
        <aside className="archive-sidebar">
          <div>
            <span className="mono-label">Archive controls</span>
            <h2 className="archive-sidebar-title">Read the record.</h2>
            <p className="archive-sidebar-copy">
              A match is a record of choices under pressure. Open one to read
              the full transcript or watch the live stream.
            </p>
          </div>
          <div className="archive-control">
            <label htmlFor="match-sort">Sort by date</label>
            <select
              id="match-sort"
              value={sort}
              onChange={(event) => changeSort(event.target.value as SortOrder)}
              className="sort-select"
              aria-label="Sort matches by date"
            >
              <option value="date_desc">Newest first</option>
              <option value="date_asc">Oldest first</option>
            </select>
          </div>
        </aside>

        <section>
          {matchesQuery.isPending && (
            <p className="loading-line">Loading match records...</p>
          )}

          {matchesQuery.isError && (
            <p className="error-line">
              Failed to load matches: {(matchesQuery.error as Error).message}
            </p>
          )}

          {!matchesQuery.isPending && !matchesQuery.isError && (
            <>
              <div className="archive-table-wrap">
                <table className="archive-table">
                  <thead>
                    <tr>
                      {COLUMNS.map((heading) => (
                        <th key={heading}>{heading}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.length === 0 && (
                      <tr>
                        <td colSpan={COLUMNS.length} className="py-10">
                          No matches recorded yet.
                        </td>
                      </tr>
                    )}
                    {rows.map((match, index) => (
                      <tr
                        key={match.id}
                        role="link"
                        tabIndex={0}
                        aria-label={`Open match details for ${match.challenge_name ?? "match"}`}
                        onClick={() => openMatch(match)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            openMatch(match);
                          }
                        }}
                      >
                        <td className="archive-index">
                          {(index + 1).toString().padStart(2, "0")}
                        </td>
                        <td className="archive-challenge">
                          {match.challenge_name ?? "—"}
                        </td>
                        <td className="archive-model prisoner">
                          {formatModel(
                            match.prisoner_provider,
                            match.prisoner_model,
                          )}
                        </td>
                        <td className="archive-model warden">
                          {formatModel(
                            match.warden_provider,
                            match.warden_model,
                          )}
                        </td>
                        <td>
                          {isLiveStatus(match.status) ? (
                            <span className="outcome-badge live">
                              {match.status}
                            </span>
                          ) : (
                            <OutcomeBadge match={match} />
                          )}
                        </td>
                        <td>{formatDuration(match.duration_seconds)}</td>
                        <td>{formatDateTime(match.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

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
                  {total} records
                </span>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
