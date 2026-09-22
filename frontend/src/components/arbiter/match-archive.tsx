import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";

import { Eyebrow } from "@/components/arbiter/app-shell";
import { Button } from "@/components/ui/button";
import { listMatches } from "@/lib/api";
import type { MatchListSchema, SortOrder } from "@/lib/dto";
import {
  formatDateTime,
  formatDuration,
  formatMatchOutcome,
  formatModel,
} from "@/lib/format";

const PAGE_SIZE = 20;

/**
 * Match statuses that are still in flight. Clicking one of these opens the
 * live spectator view instead of the recorded details, because its events are
 * still arriving.
 */
const LIVE_STATUSES = new Set(["queued", "pending", "starting", "running"]);

const COLUMNS = [
  "CHALLENGE",
  "PRISONER",
  "WARDEN",
  "OUTCOME",
  "DURATION",
  "CREATED",
];

/** The `/matches` archive: paginated match records, click one for its events. */
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
    // A match still in flight streams its events live; only a settled match
    // has a recorded history to review.
    if (LIVE_STATUSES.has(match.status)) {
      navigate({
        to: "/matches/$matchId",
        params: { matchId: match.id },
        search: {
          prisoner: formatModel(match.prisoner_provider, match.prisoner_model),
          warden: formatModel(match.warden_provider, match.warden_model),
          challenge: match.challenge_name ?? "",
        },
      });
      return;
    }
    navigate({ to: "/matches", search: { id: match.id } });
  };

  return (
    <main className="mx-auto max-w-[1600px] px-5 py-9 lg:px-8">
      <h1 className="mt-4 font-display text-3xl font-bold">
        Matches Archive
      </h1>

      <div className="mt-7 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-[11px] text-muted-foreground">
          SORT BY DATE
          <select
            value={sort}
            onChange={(event) => changeSort(event.target.value as SortOrder)}
            className="border border-border bg-panel px-3 py-2 text-[11px] text-foreground"
            aria-label="Sort matches by date"
          >
            <option value="date_desc">NEWEST FIRST</option>
            <option value="date_asc">OLDEST FIRST</option>
          </select>
        </label>
      </div>

      {matchesQuery.isPending && (
        <p className="mt-8 text-sm text-muted-foreground">
          LOADING MATCH RECORDS...
        </p>
      )}

      {matchesQuery.isError && (
        <p className="mt-8 text-sm text-destructive">
          FAILED TO LOAD MATCHES: {(matchesQuery.error as Error).message}
        </p>
      )}

      {!matchesQuery.isPending && !matchesQuery.isError && (
        <>
          <div className="mt-5 overflow-x-auto border-b border-border">
            <table className="w-full min-w-[950px] text-left text-sm">
              <thead className="bg-panel-raised text-[10px] text-muted-foreground">
                <tr>
                  {COLUMNS.map((heading) => (
                    <th key={heading} className="px-5 py-3 font-normal">
                      {heading}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr>
                    <td
                      colSpan={COLUMNS.length}
                      className="px-5 py-8 text-muted-foreground"
                    >
                      NO MATCHES RECORDED YET.
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
                    className={`cursor-pointer transition-colors hover:bg-accent/50 ${
                      index % 2 === 0 ? "bg-panel" : "bg-background"
                    }`}
                  >
                    <td className="px-5 py-4 font-bold">
                      {match.challenge_name ?? "—"}
                    </td>
                    <td className="px-5 py-4 text-primary">
                      {formatModel(
                        match.prisoner_provider,
                        match.prisoner_model,
                      )}
                    </td>
                    <td className="px-5 py-4 text-primary">
                      {formatModel(match.warden_provider, match.warden_model)}
                    </td>
                    <td className="px-5 py-4">
                      <OutcomeBadge match={match} />
                    </td>
                    <td className="px-5 py-4 text-muted-foreground">
                      {formatDuration(match.duration_seconds)}
                    </td>
                    <td className="px-5 py-4 text-muted-foreground">
                      {formatDateTime(match.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Button
              variant="secondary"
              size="sm"
              className="rounded-none"
              onClick={() => setPage((current) => Math.max(1, current - 1))}
              disabled={page <= 1}
            >
              <ChevronLeft className="size-3" />
              PREV
            </Button>
            <span className="text-[11px] text-muted-foreground">
              PAGE {pages === 0 ? 0 : page} / {pages}
            </span>
            <Button
              variant="secondary"
              size="sm"
              className="rounded-none"
              onClick={() => setPage((current) => current + 1)}
              disabled={page >= pages}
            >
              NEXT
              <ChevronRight className="size-3" />
            </Button>
            <span className="ml-auto text-[11px] text-muted-foreground">
              {total} RECORDS
            </span>
          </div>
        </>
      )}
    </main>
  );
}

/** The outcome badge shared by the archive and the match detail header. */
export function OutcomeBadge({
  match,
}: {
  match: { winner: string | null; status: string };
}) {
  const { label, muted } = formatMatchOutcome(match);
  return (
    <span className={muted ? "status-badge status-muted" : "status-badge"}>
      {label}
    </span>
  );
}
