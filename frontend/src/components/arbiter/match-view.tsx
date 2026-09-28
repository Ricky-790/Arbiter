import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { Eyebrow } from "@/components/arbiter/app-shell";
import { MatchDetails } from "@/components/arbiter/match-details";
import { MatchLiveView } from "@/components/arbiter/match-live-view";
import { MatchMasthead } from "@/components/arbiter/match-masthead";
import { getMatch } from "@/lib/api";
import type { MatchListSchema } from "@/lib/dto";
import { isLiveStatus, isPreparingStatus } from "@/lib/match-status";
import { formatDuration } from "@/lib/format";

/**
 * One entry point for one match, whatever state it is in.
 *
 * The match row is the only status channel the backend has: a start-match row
 * is created `queued` and a fork row `pending`, and both publish no events until
 * a worker has them. So the row decides which of the three views renders, and it
 * is polled while live — which also means a match that finishes mid-spectate
 * hands over to the recorded transcript on its own.
 */
export function MatchView({ matchId }: { matchId: string }) {
  const matchQuery = useQuery({
    queryKey: ["match", matchId],
    queryFn: () => getMatch(matchId),
    refetchInterval: (query) =>
      isLiveStatus(query.state.data?.status ?? "") ? 2000 : false,
  });

  const match = matchQuery.data ?? null;

  if (matchQuery.isPending) {
    return (
      <main>
        <section className="page-wrap match-masthead">
          <p className="eyebrow">Match record / {matchId.slice(0, 8)}</p>
          <h1 className="match-title">Loading the record.</h1>
          <p className="loading-line">
            Fetching this match from the archive...
          </p>
        </section>
      </main>
    );
  }

  if (matchQuery.isError || match === null) {
    return (
      <main>
        <MatchMasthead
          eyebrow={`Match record / ${matchId.slice(0, 8)}`}
          title="Match unavailable."
          error={
            <p className="match-error">
              Failed to load match:{" "}
              {matchQuery.error instanceof Error
                ? matchQuery.error.message
                : "This match could not be found."}
            </p>
          }
        />
        <section className="page-wrap event-section">
          <Link to="/matches" className="button-secondary">
            Back to the archive
          </Link>
        </section>
      </main>
    );
  }

  if (isPreparingStatus(match.status)) {
    return <MatchPreparing match={match} />;
  }
  if (isLiveStatus(match.status)) {
    return <MatchLiveView match={match} />;
  }
  return <MatchDetails match={match} />;
}

/**
 * The gap between "queued" and "running".
 *
 * A start-match row is written `queued` and nothing is published until a worker
 * has picked it up, so opening the stream now would only ever show `stream_open`
 * and keep-alives. The gate is the whole reason this state is worth its own
 * screen, and it polls the row until the match is actually hosted.
 */
function MatchPreparing({ match }: { match: MatchListSchema }) {
  const waited = useWaitedSeconds(match.id);

  return (
    <main>
      <MatchMasthead
        eyebrow={`Match setup / ${match.id.slice(0, 8)}`}
        title={match.challenge_name ?? "Sandbox run"}
        status={<span className="board-status is-live">Preparing</span>}
        metrics={[
          { label: "Match state", value: match.status, signal: true },
          { label: "Waited", value: formatDuration(waited) },
          { label: "Match ID", value: match.id },
        ]}
      />

      <section className="page-wrap event-section">
        <div className="match-gate">
          <div className="match-gate-mark" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div className="match-gate-copy">
            <Eyebrow>Match setup</Eyebrow>
            <h2 className="match-gate-title">Waiting for a worker.</h2>
            <p className="match-gate-text">
              This match has been queued but no worker has picked it up yet, so
              there is nothing to stream. The page rechecks on its own and
              starts spectating the moment it goes live.
            </p>
            <p className="mono-label">
              Waited {formatDuration(waited)} · rechecking every 2s · this page
              will start streaming on its own
            </p>
          </div>
        </div>
      </section>
    </main>
  );
}

/** Whole seconds since the match was opened, for the preparing state. */
function useWaitedSeconds(matchId: string): number {
  const [waited, setWaited] = useState(0);

  useEffect(() => {
    setWaited(0);
    const timer = setInterval(() => {
      setWaited((current) => current + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [matchId]);

  return waited;
}
