/**
 * TypeScript mirror of `backend/app/api/schemas/dto_models.py`.
 *
 * Keep these in sync when the Pydantic schemas change: each type here matches
 * one response/request model one-to-one, including nullable fields.
 */

/** Arbitrary JSON object as returned for the JSONB columns. */
export type JsonObject = Record<string, unknown>;

/** `ChallengeSummary` — list view of a challenge. */
export type ChallengeSummary = {
  id: string;
  name: string;
  description: string;
  win_condition: string;
};

/** `ChallengeSchema` — full challenge row. */
export type ChallengeSchema = {
  id: string;
  name: string;
  description: string;
  win_condition: string;
  challenge_type: string;
  verification_config: JsonObject;
  flag: JsonObject;
  flag_structure: JsonObject;
  verifier_script: string | null;
  sandbox_config: JsonObject;
  files: JsonObject;
  env_vars: JsonObject;
  setup_script: string | null;
  created_at: string;
  updated_at: string;
};

/** `MatchSchema` — full match row. */
export type MatchSchema = {
  id: string;
  challenge_id: string;
  prisoner_model: string;
  prisoner_provider: string;
  warden_model: string;
  warden_provider: string;
  status: string;
  winner: string | null;
  win_condition: string;
  duration_seconds: number | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
};

/** `MatchEventSchema` — one persisted match event. */
export type MatchEventSchema = {
  id: string;
  match_id: string;
  actor: string;
  event_type: string;
  action: JsonObject;
  result: JsonObject | null;
  timestamp: string;
};

/** `StartMatchRequest` — body for `POST /api/v1/matches/start-match`. */
export type StartMatchRequest = {
  challenge_id: string;
  prisoner_model: string;
  warden_model: string;
};

/** `StartMatchResponse` — acknowledged queued match. */
export type StartMatchResponse = {
  match_id: string;
  status: string;
};

/** `PaginationMeta` — paging envelope shared by list responses. */
export type PaginationMeta = {
  page: number;
  page_size: number;
  total: number;
  pages: number;
};

/** `MatchListSchema` — a match row plus the joined challenge name. */
export type MatchListSchema = MatchSchema & {
  challenge_name: string | null;
};

/** `MatchListResponse` — one page of matches. */
export type MatchListResponse = PaginationMeta & {
  items: MatchListSchema[];
};

/** `MatchEventListResponse` — one page of a single match's events. */
export type MatchEventListResponse = PaginationMeta & {
  items: MatchEventSchema[];
};

/** Date-sort direction accepted by the paginated list endpoints. */
export type SortOrder = "date_asc" | "date_desc";

/**
 * One Server-Sent Event payload from `POST /api/v1/matches/spectate`.
 *
 * The envelope always carries `match_id` and `type`. Which extra fields are
 * present depends on `type` (see the Engine's `_record` calls):
 *
 * - `stream_open` / `stream_closed` / `stream_error` — transport only
 * - `match_started` — match is running
 * - `agent_message` — `actor`, `content`
 * - `tool_result` — `actor`, `tool`, `arguments`, `success`, `exit_code`, `error`
 * - `trap_triggered` — `trap`, `reaction_until`
 * - `match_finished` — `winner`, `end_reason`
 * - `agent_retry` / `agent_error` / `agent_unavailable` — `reason`, `status`,
 *   `attempt`, `max_attempts`, `wait_seconds`, `detail`
 */
export type SpectateEvent = {
  match_id: string;
  type: string;
  timestamp?: string;
  actor?: string;
  content?: string;
  tool?: string;
  arguments?: JsonObject;
  success?: boolean;
  exit_code?: number | null;
  error?: string | null;
  reason?: string;
  status?: number;
  attempt?: number;
  max_attempts?: number;
  wait_seconds?: number;
  detail?: string;
  trap?: string | null;
  reaction_until?: string;
  winner?: string | null;
  end_reason?: string | null;
  [key: string]: unknown;
};

/** Which side of the match an event belongs to. */
export type ActorRole = "prisoner" | "warden";
