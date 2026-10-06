/**
 * Typed client for the Arbiter HTTP API.
 *
 * The base URL comes from `VITE_API_BASE_URL` and falls back to the local
 * backend, so the app works out of the box without an `.env`.
 */

import {
  encryptApiKeyFields,
  redactSecrets,
  resetApiKeyTransport,
} from "@/lib/crypto";
import type {
  AvailableModelsResponse,
  ChallengeSchema,
  ChallengeSummary,
  ConversationEntry,
  ForkDetailSchema,
  ForkListResponse,
  ForkMatchRequest,
  ForkSchema,
  MatchEventListResponse,
  MatchEventSchema,
  MatchListResponse,
  MatchListSchema,
  MatchSide,
  MatchSummaryResponse,
  ModelCheckRequest,
  ModelCheckResponse,
  PageMeta,
  ReviewEvent,
  ReviewMatchEvent,
  ReviewStrategyRequest,
  SaveStrategyRequest,
  SortOrder,
  SpectateEvent,
  StartForkMatchRequest,
  StartMatchRequest,
  StartMatchResponse,
  StrategyDetailResponse,
  StrategySchema,
  ThoughtRecord,
  ToolCallRecord,
  TrapEvent,
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

async function request<T>(
  path: string,
  init?: RequestInit,
  /** Plaintext api keys this request carried, scrubbed out of its error text. */
  secrets: readonly string[] = [],
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    if (response.status === 400) {
      // A 400 on a request carrying an api key is most often a key this
      // deployment can no longer open — a rotation. Drop the cached public key so
      // the next attempt encrypts with the current one instead of failing forever.
      resetApiKeyTransport();
    }
    throw new ApiError(
      redactSecrets(await errorDetail(response), secrets),
      response.status,
    );
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

/**
 * `GET /api/v1/matches/models` — the selectable catalogue: each provider and the
 * models it offers. Every model is BYOK, so the caller supplies the key. These
 * are suggestions; a pasted name is accepted too and confirmed by `verifyModel`.
 */
export function listModels(): Promise<AvailableModelsResponse> {
  return request<AvailableModelsResponse>("/api/v1/matches/models");
}

/**
 * `POST /api/v1/matches/verify-model` — ask whether a provider serves a model.
 *
 * The browser cannot ask the provider directly: CORS blocks it, and sending the
 * key from the page would expose it. The backend makes the call with the key.
 * A model that cannot be confirmed comes back as `exists: false`, not an error.
 */
export async function verifyModel(
  payload: ModelCheckRequest,
  signal?: AbortSignal,
): Promise<ModelCheckResponse> {
  const { body, secrets } = await encryptApiKeyFields(payload, ["api_key"]);
  return request<ModelCheckResponse>(
    "/api/v1/matches/verify-model",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      // `RequestInit.signal` is `AbortSignal | null`, not optional here.
      signal: signal ?? null,
    },
    secrets,
  );
}

/** `POST /api/v1/matches/start-match` — queue a match, returns its id. */
export async function startMatch(
  payload: StartMatchRequest,
): Promise<StartMatchResponse> {
  const { body, secrets } = await encryptApiKeyFields(payload, [
    "prisoner_api_key",
    "warden_api_key",
  ]);
  return request<StartMatchResponse>(
    "/api/v1/matches/start-match",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    secrets,
  );
}

/**
 * `POST /api/v1/matches/fork` — save a fork point on a finished match.
 *
 * This only starts the fork *creation* process: the backend creates a checkpoint
 * row, queues the rebuild of its sandbox snapshot and the two conversations, and
 * returns `202`. No match is started and no models or keys are involved — a new
 * match is started from the fork later via `startFromFork`.
 */
export function forkMatch(payload: ForkMatchRequest): Promise<ForkSchema> {
  return request<ForkSchema>("/api/v1/matches/fork", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/**
 * `GET /api/v1/matches/forks` — one page of saved forks, newest first.
 *
 * Omit `matchId` for every saved fork, which is what the forks tab shows.
 */
export function listForks({
  matchId,
  page = 1,
  pageSize = 20,
}: { matchId?: string } & ListPageParams = {}): Promise<ForkListResponse> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (matchId !== undefined && matchId !== "") {
    query.set("match_id", matchId);
  }
  return request<ForkListResponse>(`/api/v1/matches/forks?${query}`);
}

/**
 * `GET /api/v1/matches/fork?fork_id=...` — one fork with the state a match is
 * started from: the challenge, the parent's models, the turns behind the branch
 * point, and each agent's conversation up to there.
 */
export function getFork(forkId: string): Promise<ForkDetailSchema> {
  const query = new URLSearchParams({ fork_id: forkId });
  return request<ForkDetailSchema>(`/api/v1/matches/fork?${query}`);
}

/**
 * `POST /api/v1/matches/start-from-fork` — queue a new match from a saved fork.
 *
 * The fork supplies the challenge, the sandbox state and the conversation each
 * agent resumes from; the body supplies the models, tips and keys, so the same
 * fork can back any number of experiments.
 */
export async function startFromFork(
  payload: StartForkMatchRequest,
): Promise<StartMatchResponse> {
  const { body, secrets } = await encryptApiKeyFields(payload, [
    "prisoner_api_key",
    "warden_api_key",
  ]);
  return request<StartMatchResponse>(
    "/api/v1/matches/start-from-fork",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
    secrets,
  );
}

/**
 * `POST /api/v1/strategies/save-strategy` — promote one side's strategy into
 * the library.
 *
 * The body names the match and the side and nothing else: the text is read off
 * the match row, so what is saved is exactly what the match ran, and the
 * one-line description is derived from that text rather than accepted. Safe to
 * call twice — a repeat returns the row that already exists and repairs the
 * link back onto the match.
 */
export function saveStrategy(
  payload: SaveStrategyRequest,
): Promise<StrategySchema> {
  return request<StrategySchema>("/api/v1/strategies/save-strategy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/**
 * `GET /api/v1/strategies/all` — one page of the whole library, newest first.
 *
 * `challengeId` narrows it to one challenge, which is the usual question: a
 * strategy only means anything against the challenge it was played on. An id
 * that matches nothing is an empty page rather than an error, since it is a
 * filter and not a lookup.
 *
 * The library grows for as long as matches are run, so this is paged.
 */
export function listStrategies({
  challengeId,
  offset = 0,
  limit = 20,
}: { challengeId?: string } & PageParams = {}): Promise<
  PageMeta<StrategySchema>
> {
  const query = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
  });
  if (challengeId !== undefined && challengeId !== "") {
    query.set("challenge_id", challengeId);
  }
  return request<PageMeta<StrategySchema>>(`/api/v1/strategies/all?${query}`);
}

/**
 * `GET /api/v1/strategies?strategy_id=...` — one strategy and its lineage.
 *
 * Returns the strategy, the match it was promoted from, and a page of the
 * matches started from it.
 */
export function getStrategy({
  strategyId,
  offset = 0,
  limit = 20,
}: { strategyId: string } & PageParams): Promise<StrategyDetailResponse> {
  const query = new URLSearchParams({
    strategy_id: strategyId,
    offset: String(offset),
    limit: String(limit),
  });
  return request<StrategyDetailResponse>(`/api/v1/strategies?${query}`);
}

/** Query options shared by the offset/limit listings. */
export type PageParams = {
  offset?: number;
  limit?: number;
};

/** How many rows a walk-all helper pulls per request. */
const REVIEW_PAGE_SIZE = 100;

/** `GET /api/v1/reviewer/conversation` — one page of an agent's conversation. */
export function listConversation(
  matchId: string,
  user: MatchSide,
  params: PageParams = {},
): Promise<PageMeta<ConversationEntry>> {
  return request<PageMeta<ConversationEntry>>(
    `/api/v1/reviewer/conversation?${reviewQuery(matchId, user, params)}`,
  );
}

/** `GET /api/v1/reviewer/tool-calls` — one page of an agent's tool calls. */
export function listToolCalls(
  matchId: string,
  user: MatchSide,
  params: PageParams = {},
): Promise<PageMeta<ToolCallRecord>> {
  return request<PageMeta<ToolCallRecord>>(
    `/api/v1/reviewer/tool-calls?${reviewQuery(matchId, user, params)}`,
  );
}

/** `GET /api/v1/reviewer/thoughts` — one page of an agent's narration. */
export function listThoughts(
  matchId: string,
  user: MatchSide,
  params: PageParams = {},
): Promise<PageMeta<ThoughtRecord>> {
  return request<PageMeta<ThoughtRecord>>(
    `/api/v1/reviewer/thoughts?${reviewQuery(matchId, user, params)}`,
  );
}

/** `GET /api/v1/reviewer/traps` — one page of trap firings, match-wide. */
export function listTraps(
  matchId: string,
  params: PageParams = {},
): Promise<PageMeta<TrapEvent>> {
  const query = new URLSearchParams({
    match_id: matchId,
    offset: String(params.offset ?? 0),
    limit: String(params.limit ?? REVIEW_PAGE_SIZE),
  });
  return request<PageMeta<TrapEvent>>(`/api/v1/reviewer/traps?${query}`);
}

/** `GET /api/v1/reviewer/events` — one page of an agent's raw events. */
export function listReviewEvents(
  matchId: string,
  user: MatchSide,
  params: PageParams = {},
): Promise<PageMeta<ReviewMatchEvent>> {
  return request<PageMeta<ReviewMatchEvent>>(
    `/api/v1/reviewer/events?${reviewQuery(matchId, user, params)}`,
  );
}

function reviewQuery(
  matchId: string,
  user: MatchSide,
  params: PageParams,
): string {
  return new URLSearchParams({
    match_id: matchId,
    user,
    offset: String(params.offset ?? 0),
    limit: String(params.limit ?? REVIEW_PAGE_SIZE),
  }).toString();
}

/**
 * Every row of a reviewer listing.
 *
 * The endpoints are paged at the reviewer's own ceiling; the review page reads a
 * whole match at once, so this walks the pages until it has them all. An empty
 * answer is legitimate — a match recorded before conversations were kept has
 * none — so a short page simply ends the walk.
 */
async function listAllReview<T>(
  fetchPage: (offset: number) => Promise<PageMeta<T>>,
): Promise<T[]> {
  const rows: T[] = [];
  for (let offset = 0; offset <= 10_000; offset += REVIEW_PAGE_SIZE) {
    const page = await fetchPage(offset);
    rows.push(...page.items);
    if (!page.has_more || page.items.length === 0) break;
  }
  return rows;
}

export function listAllConversation(
  matchId: string,
  user: MatchSide,
): Promise<ConversationEntry[]> {
  return listAllReview((offset) => listConversation(matchId, user, { offset }));
}

export function listAllToolCalls(
  matchId: string,
  user: MatchSide,
): Promise<ToolCallRecord[]> {
  return listAllReview((offset) => listToolCalls(matchId, user, { offset }));
}

export function listAllThoughts(
  matchId: string,
  user: MatchSide,
): Promise<ThoughtRecord[]> {
  return listAllReview((offset) => listThoughts(matchId, user, { offset }));
}

export function listAllTraps(matchId: string): Promise<TrapEvent[]> {
  return listAllReview((offset) => listTraps(matchId, { offset }));
}

export function listAllReviewEvents(
  matchId: string,
  user: MatchSide,
): Promise<ReviewMatchEvent[]> {
  return listAllReview((offset) => listReviewEvents(matchId, user, { offset }));
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
 * `GET /api/v1/reviewer/summary` — everything about a match that stays small.
 *
 * Always answers with a list, one entry per side summarised, so its shape never
 * depends on the request: this asks for both, Prisoner first, and each entry is
 * scoped entirely to its own side — its stats, its strategy, its opening
 * message — with no opponent block. Comparing the two sides is reading two
 * entries of the same shape. Anything that grows with the length of the match
 * has its own paginated endpoint instead, so this stays bounded.
 */
export function getMatchSummary(
  matchId: string,
): Promise<MatchSummaryResponse[]> {
  const query = new URLSearchParams({ match_id: matchId });
  return request<MatchSummaryResponse[]>(`/api/v1/reviewer/summary?${query}`);
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
 * Consume a Server-Sent Events response body.
 *
 * Both streaming endpoints are `POST`, so the browser `EventSource` cannot be
 * used; this reads the body as a stream and parses SSE frames. Resolves when the
 * backend closes the stream, rejects on transport failure, and stops when
 * `signal` is aborted.
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
  // The spectator stream carries no api key, so there is nothing to scrub.
  await consumeEventStream(response, onEvent);
}

/**
 * `POST /api/v1/strategies/review` — run the strategy reviewer over one match
 * and stream what it does and what it concludes.
 *
 * Everything is validated before the stream opens — unknown provider, a missing
 * key, a model the provider does not serve, an unknown strategy or match, or a
 * strategy played on a different challenge — so those arrive as a plain 4xx
 * rather than an error frame halfway through. Once the stream is open, progress
 * arrives as `review_tool_call`/`review_tool_result` frames and the run ends with
 * exactly one `review_finished` (carrying the proposed strategy) or
 * `review_error`.
 *
 * Nothing is saved: what comes back is a proposal.
 */
export async function reviewStrategy(
  payload: ReviewStrategyRequest,
  onEvent: (event: ReviewEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const { body, secrets } = await encryptApiKeyFields(payload, ["api_key"]);
  const response = await fetch(`${API_BASE_URL}/api/v1/strategies/review`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(body),
    signal,
  });
  if (response.status === 400) {
    // Same self-heal as `request`: a 400 here is most likely a rotated key.
    resetApiKeyTransport();
  }
  await consumeEventStream(response, onEvent, secrets);
}

/**
 * Read one SSE response to its end, handing each frame to `onEvent`.
 *
 * `secrets` are any plaintext api keys the request carried, so a failure before
 * the stream opens cannot report one back in its message.
 */
async function consumeEventStream<T>(
  response: Response,
  onEvent: (event: T) => void,
  secrets: readonly string[] = [],
): Promise<void> {
  if (!response.ok) {
    throw new ApiError(
      redactSecrets(await errorDetail(response), secrets),
      response.status,
    );
  }
  if (response.body === null) {
    throw new ApiError("Stream has no body", response.status);
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
      emitFrame(buffer.slice(0, boundary), onEvent);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

function emitFrame<T>(frame: string, onEvent: (event: T) => void): void {
  const data = frame
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice("data:".length).trimStart())
    .join("\n");
  if (data.length === 0) return; // Comment/keep-alive frame.
  try {
    onEvent(JSON.parse(data) as T);
  } catch {
    // A malformed frame must not kill the stream.
  }
}
