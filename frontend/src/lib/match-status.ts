/**
 * Match status vocabulary, shared by the archive, the unified match view and
 * the fork gate.
 *
 * Mirrors `MATCH_STATUSES` in `backend/app/db/models/match.py`, but only with
 * the non-terminal half: `backend/app/api/routes/matches.py` writes `queued`
 * for a start-match and `pending` for a fork, then the workers move the row on
 * to `running` and finally `completed` or `failed`.
 */

/** Statuses whose match is still being set up or is still running. */
export const LIVE_STATUSES = new Set([
  "queued",
  "pending",
  "starting",
  "running",
]);

/**
 * Statuses that produce no spectator events yet.
 *
 * A queued match is waiting for the match worker. A pending match is a fork:
 * the fork worker is replaying the parent's history into a fresh snapshot
 * first, and replay mode suppresses event emission entirely, so the stream
 * would otherwise sit silent.
 */
export const PREPARING_STATUSES = new Set(["queued", "pending"]);

/** Whether the match is queued, preparing, or running. */
export function isLiveStatus(status: string): boolean {
  return LIVE_STATUSES.has(status);
}

/** Whether the match has no host yet, so streaming would just show nothing. */
export function isPreparingStatus(status: string): boolean {
  return PREPARING_STATUSES.has(status);
}

/**
 * Whether the recorded view may offer forking.
 *
 * The backend enforces this too: `POST /matches/fork` answers 409 unless the
 * parent's status is terminal, because a match still being hosted is still
 * writing the history a fork would capture. The UI gate keeps the button from
 * offering something the server will refuse.
 */
export function canFork(status: string): boolean {
  return !LIVE_STATUSES.has(status);
}

/**
 * A saved fork's lifecycle, mirroring `FORK_STATUSES` in
 * `backend/app/db/models/match_fork.py`.
 */
export const FORK_STATUSES = new Set(["pending", "ready", "failed"]);

/** Whether the fork's snapshot is still being rebuilt. */
export function isForkPending(status: string): boolean {
  return status === "pending";
}

/** Whether a match can be started from this fork. */
export function isForkReady(status: string): boolean {
  return status === "ready";
}
