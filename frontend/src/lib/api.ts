/**
 * Typed client for the Arbiter HTTP API.
 *
 * The base URL comes from `VITE_API_BASE_URL` and falls back to the local
 * backend, so the app works out of the box without an `.env`.
 */

import type {
  ChallengeSchema,
  ChallengeSummary,
  MatchEventListResponse,
  MatchEventSchema,
  MatchListResponse,
  MatchListSchema,
  SortOrder,
  SpectateEvent,
  StartMatchRequest,
  StartMatchResponse,
} from "./dto";

const configuredBaseUrl =
  import.meta.env["VITE_API_BASE_URL"] ?? "http://localhost:8000";

/** Backend origin, without a trailing slash. */
export const API_BASE_URL = String(configuredBaseUrl).replace(/\/+$/, "");

/** Non-2xx response from the backend, carrying its `detail` message. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status);
  }
  return (await response.json()) as T;
}

async function errorDetail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (body.detail !== undefined) return JSON.stringify(body.detail);
  } catch {
    // Non-JSON error body; fall through to the status text.
  }
  return response.statusText || `Request failed (${response.status})`;
}

/** `GET /api/v1/challenges/` — all challenges, list view. */
export function listChallenges(): Promise<ChallengeSummary[]> {
  return request<ChallengeSummary[]>("/api/v1/challenges/");
}

/** `GET /api/v1/challenges/challenge?challenge_id=...` — full challenge row. */
export function getChallenge(challengeId: string): Promise<ChallengeSchema> {
  const query = new URLSearchParams({ challenge_id: challengeId });
  return request<ChallengeSchema>(`/api/v1/challenges/challenge?${query}`);
}

/** `GET /api/v1/matches/free-models` — selectable `provider/model` keys. */
export function listFreeModels(): Promise<string[]> {
  return request<string[]>("/api/v1/matches/free-models");
}

/** `POST /api/v1/matches/start-match` — queue a match, returns its id. */
export function startMatch(
  payload: StartMatchRequest,
): Promise<StartMatchResponse> {
  return request<StartMatchResponse>("/api/v1/matches/start-match", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/** Query options shared by the paginated list endpoints. */
export type ListPageParams = {
  page?: number;
  pageSize?: number;
  sort?: SortOrder;
};

/** `GET /api/v1/matches/` — one page of the match archive. */
export function listMatches({
  page = 1,
  pageSize = 20,
  sort = "date_desc",
}: ListPageParams = {}): Promise<MatchListResponse> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    sort,
  });
  return request<MatchListResponse>(`/api/v1/matches/?${query}`);
}

/** `GET /api/v1/matches/events` — one page of a match's persisted events. */
export function listMatchEvents(
  matchId: string,
  { page = 1, pageSize = 20, sort = "date_asc" }: ListPageParams = {},
): Promise<MatchEventListResponse> {
  const query = new URLSearchParams({
    match_id: matchId,
    page: String(page),
    page_size: String(pageSize),
    sort,
  });
  return request<MatchEventListResponse>(`/api/v1/matches/events?${query}`);
}

/** `GET /api/v1/matches/match?match_id=...` — one match row. */
export function getMatch(matchId: string): Promise<MatchListSchema> {
  const query = new URLSearchParams({ match_id: matchId });
  return request<MatchListSchema>(`/api/v1/matches/match?${query}`);
}

/**
 * Every persisted event for a match.
 *
 * The events endpoint is paginated; the detail view shows the whole history at
 * once, so this walks the pages until it has them all.
 */
export async function listAllMatchEvents(
  matchId: string,
  sort: SortOrder = "date_asc",
): Promise<MatchEventSchema[]> {
  const pageSize = 100;
  const maxPages = 100;
  const events: MatchEventSchema[] = [];
  for (let page = 1; page <= maxPages; page += 1) {
    const response = await listMatchEvents(matchId, { page, pageSize, sort });
    events.push(...response.items);
    if (page >= response.pages || response.items.length === 0) break;
  }
  return events;
}

/** SSE endpoint for one match's live event stream. */
export function spectateUrl(matchId: string): string {
  const query = new URLSearchParams({ match_id: matchId });
  return `${API_BASE_URL}/api/v1/matches/spectate?${query}`;
}

/**
 * Consume the spectate endpoint's Server-Sent Events.
 *
 * The endpoint is `POST`, so the browser `EventSource` API cannot be used;
 * this reads the response body as a stream and parses SSE frames. Resolves
 * when the backend closes the stream, rejects on transport failure, and stops
 * when `signal` is aborted.
 */
export async function streamMatchEvents(
  matchId: string,
  onEvent: (event: SpectateEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(spectateUrl(matchId), {
    method: "POST",
    headers: { Accept: "text/event-stream" },
    signal,
  });
  if (!response.ok) {
    throw new ApiError(await errorDetail(response), response.status);
  }
  if (response.body === null) {
    throw new ApiError("Spectator stream has no body", response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      emitFrame(frame, onEvent);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

function emitFrame(
  frame: string,
  onEvent: (event: SpectateEvent) => void,
): void {
  const data = frame
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice("data:".length).trimStart())
    .join("\n");
  if (data.length === 0) return; // Comment/keep-alive frame.
  try {
    onEvent(JSON.parse(data) as SpectateEvent);
  } catch {
    // A malformed frame must not kill the spectator stream.
  }
}
