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
  /** Each side names its provider and model separately. */
  prisoner_provider: string;
  prisoner_model: string;
  warden_provider: string;
  warden_model: string;
  /** Optional operator tips appended to the agent's role instructions. */
  prisoner_suggestions: string | null;
  warden_suggestions: string | null;
  /**
   * Provider key for each side, used for that match only. Every model is BYOK,
   * so both are required.
   */
  prisoner_api_key: string | null;
  warden_api_key: string | null;
};

/** `ProviderModels` — one provider and the models it offers, in display order. */
export type ProviderModels = {
  provider: string;
  models: string[];
};

/** `AvailableModelsResponse` — the selectable catalogue, nested by provider. */
export type AvailableModelsResponse = {
  providers: ProviderModels[];
};

/** `ModelCheckRequest` — body for `POST /api/v1/matches/verify-model`. */
export type ModelCheckRequest = {
  provider: string;
  model: string;
  api_key: string;
};

/**
 * `ModelCheckResponse` — whether a model name was confirmed with its provider.
 *
 * `exists: false` is a normal answer, not an error, so the reason can be shown
 * beside the field. `reason` is `not_found`, `key_rejected` or `unreachable`.
 */
export type ModelCheckResponse = {
  exists: boolean;
  reason: string | null;
  detail: string | null;
};

/** `StartMatchResponse` — acknowledged queued match. */
export type StartMatchResponse = {
  match_id: string;
  status: string;
};

/** `ForkMatchRequest` — body for `POST /api/v1/matches/fork`. */
export type ForkMatchRequest = {
  /** The finished match whose state is captured. */
  parent_match_id: string;
  /** Branch point; snapped forward to the end of its tool-call batch. */
  match_event_id: string;
};

/**
 * `ForkSchema` — one saved fork: a checkpoint a new match can be started from.
 *
 * A fork carries no models and never runs. The backend rebuilds its sandbox
 * snapshot and each agent's conversation, then flips `status` to `ready`.
 */
export type ForkSchema = {
  id: string;
  parent_match_id: string;
  /** The effective branch point, after snapping to a model response's end. */
  branch_event_id: string;
  branch_event_timestamp: string;
  /** `pending` while rebuilding, then `ready` or `failed`. */
  status: string;
  created_at: string;
};

/** `ForkDetailSchema` — a fork plus everything the fork page starts a match from. */
export type ForkDetailSchema = ForkSchema & {
  challenge_id: string;
  /** The parent match's choices, offered as the picker's starting point. */
  prisoner_provider: string | null;
  prisoner_model: string | null;
  warden_provider: string | null;
  warden_model: string | null;
  /** The tool-call history behind the branch point. */
  latest_turns: MatchEventSchema[];
  /**
   * Each agent's stored conversation, cut at the branch point, as pydantic-ai
   * message dumps. `null` for rows recorded before conversations were kept.
   */
  prisoner_messages: JsonObject[] | null;
  warden_messages: JsonObject[] | null;
};

/** `ForkListResponse` — one page of saved forks, newest first. */
export type ForkListResponse = PaginationMeta & {
  items: ForkSchema[];
};

/**
 * `StartForkMatchRequest` — body for `POST /api/v1/matches/start-from-fork`.
 *
 * The same choices as `start-match`, except the challenge and the resumed state
 * come from the fork instead of the caller.
 */
export type StartForkMatchRequest = {
  fork_id: string;
  prisoner_provider: string;
  prisoner_model: string;
  warden_provider: string;
  warden_model: string;
  prisoner_suggestions: string | null;
  warden_suggestions: string | null;
  prisoner_api_key: string | null;
  warden_api_key: string | null;
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
