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
  /**
   * Free-text tips appended to the agent's role instructions, when the operator
   * wrote their own. Null when the side is running a saved strategy instead —
   * the two are alternatives, not a pair.
   */
  prisoner_suggestions: string | null;
  warden_suggestions: string | null;
  /**
   * A saved strategy to run this side with, instead of its own suggestions. An
   * explicit id wins over suggestions sent for the same side.
   */
  prisoner_strategy_id: string | null;
  warden_strategy_id: string | null;
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
  /** As on `start-match`: a saved strategy instead of this side's own tips. */
  prisoner_strategy_id: string | null;
  warden_strategy_id: string | null;
  prisoner_api_key: string | null;
  warden_api_key: string | null;
};

/** `MatchSide` — which agent a reviewer question or a stat block is about. */
export type MatchSide = "prisoner" | "warden";

/** `MatchOverview` — the match row as the reviewer reads it. */
export type MatchOverview = {
  match_id: string;
  status: string;
  winner: string | null;
  win_condition: string;
  challenge_id: string;
  challenge_name: string | null;
  /** The challenge's own description, so no second read is needed. */
  challenge_description: string | null;
  prisoner_provider: string;
  prisoner_model: string;
  warden_provider: string;
  warden_model: string;
  /** The strategy each side ran with, keyed by side. */
  strategy: Record<string, string>;
  /** `strategies.id` per side, once promoted into the library. */
  strategy_id: Record<string, string>;
  /** Set when the match was started from a fork. */
  parent_match_id: string | null;
  branch_event_id: string | null;
  duration_seconds: number | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
};

/**
 * `SideStats` — what one side spent and did.
 *
 * `credits_remaining` and `tool_calls` come from the summary the Engine wrote as
 * the match closed, so they are `null` for a match recorded before that summary
 * existed. The breakdown fields are counted from events instead, so they are
 * always present.
 */
export type SideStats = {
  actor: string;
  credits_remaining: number | null;
  tool_calls: number | null;
  tool_calls_by_name: Record<string, number>;
  successful_tool_calls: number;
  failed_tool_calls: number;
  /** Actions the Engine refused before running them. */
  rejected_tool_calls: number;
  /** Prisoner only; `null` for the Warden, which is caught by nothing. */
  times_trapped: number | null;
  /** Warden only; `null` for the Prisoner, which arms none. */
  traps_armed: number | null;
  /** Warden only; `null` for the Prisoner. */
  traps_triggered: number | null;
};

/** `AgentBriefing` — the opening message one agent was given. */
export type AgentBriefing = {
  actor: string;
  strategy: string | null;
  briefing: string;
};

/**
 * `MatchSummaryResponse` — everything bounded by one side of one match.
 *
 * The endpoint always answers with a list of these, one entry per side
 * summarised, Prisoner first, so its shape never depends on the request: omit
 * `user` and both come back, ask for one side and the list holds that entry
 * alone. Every entry is scoped entirely to its own side — `stats`, `strategy`,
 * `briefing` — with no opponent block, so comparing the sides means reading two
 * entries of the same shape. `match` is the shared match row and carries the
 * full strategy map.
 */
export type MatchSummaryResponse = {
  match: MatchOverview;
  /** The side this entry describes. */
  user: MatchSide;
  stats: SideStats;
  /** The strategy this side ran, exactly as the match ran it. */
  strategy: string | null;
  /** Which trap tool fired and how often; shared, not per side. */
  triggered_trap_tools: Record<string, number>;
  briefing: AgentBriefing | null;
};

/**
 * `SaveStrategyRequest` — body for `POST /api/v1/strategies/save-strategy`.
 *
 * The strategy text is not sent: the backend reads it off the match row, so what
 * gets saved is exactly what the match ran, and no description is accepted for
 * the same reason.
 */
export type SaveStrategyRequest = {
  match_id: string;
  /** Which side's strategy to promote. */
  user: MatchSide;
};

/** `StrategySchema` — one strategy promoted out of a finished match. */
export type StrategySchema = {
  id: string;
  match_id: string;
  challenge_id: string;
  /** Joined in for display: a strategy only means something on its challenge. */
  challenge_name: string | null;
  user: string;
  /** The label the strategy is listed under, derived from its own first line. */
  one_line_description: string;
  strategy: string;
  /** The library strategy this one evolved from, when there was one. */
  origin_strat_id: string | null;
  created_at: string;
};

/**
 * `StrategyMatchSummary` — the few facts about a match that a strategy's lineage
 * needs. Deliberately not the whole match: a lineage lists runs, it does not
 * carry their history.
 */
export type StrategyMatchSummary = {
  match_id: string;
  challenge_name: string | null;
  prisoner_model: string;
  warden_model: string;
  winner: string | null;
};

/**
 * `StrategyDetailResponse` — one strategy and where it has been.
 *
 * `parent_match` is the match it was promoted *from*, so its wording can be read
 * against the run that produced it. `used_in_matches` is a page of the matches
 * started from it, newest first; the parent is deliberately not among them,
 * having run the wording before the strategy existed.
 */
export type StrategyDetailResponse = {
  strategy: StrategySchema;
  parent_match: StrategyMatchSummary | null;
  used_in_matches: PageMeta<StrategyMatchSummary>;
};

/**
 * `Page` — the reviewer's paging envelope, used by the strategy listings.
 *
 * Deliberately offset/limit rather than the `PaginationMeta` page/page_size
 * vocabulary the match and fork listings use, so the HTTP answer and an agent
 * tool result are the same object.
 */
export type PageMeta<T> = {
  items: T[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
};

/**
 * `ConversationEntry` — one step of an agent's stored conversation.
 *
 * The stored form is pydantic-ai's own message dump; this is the same content
 * resolved into one row per step, so it can be paged without parsing the wire
 * format. `kind` is `user-prompt`, `tool-call`, `tool-return` or `text`.
 */
export type ConversationEntry = {
  index: number;
  kind: string;
  /** `prisoner` / `warden` for a prompt, else null. */
  actor: string | null;
  /** Text the agent read or wrote, when the step carries any. */
  text: string | null;
  tool_name: string | null;
  tool_call_id: string | null;
  /** Arguments of a tool call, or the payload of a tool return. */
  content: JsonObject | null;
};

/** `ToolCallRecord` — one requested tool call, whatever its outcome. */
export type ToolCallRecord = {
  event_id: string;
  timestamp: string;
  actor: string;
  tool: string | null;
  arguments: JsonObject;
  /** Null for a call the Engine refused before running. */
  success: boolean | null;
  exit_code: number | null;
  error: string | null;
  failure_category: string | null;
};

/**
 * `ThoughtRecord` — one piece of narration an agent produced for the match log.
 *
 * This is what the agent chose to report. Arbiter does not capture or store a
 * model's private chain of thought, so there is none behind this.
 */
export type ThoughtRecord = {
  event_id: string;
  timestamp: string;
  actor: string;
  content: string;
};

/** `TrapEvent` — one trap firing, and where in the match it happened. */
export type TrapEvent = {
  event_id: string;
  timestamp: string;
  /** The trap tool that fired. */
  trap: string | null;
  /** The path or process name it was watching. */
  target: string | null;
  /** The Prisoner's turn in progress when it fired. */
  prisoner_turn: number | null;
  /** The Warden's turn at the same moment. */
  warden_turn: number | null;
};

/**
 * `MatchEventRecord` — a raw match event, the catch-all for whatever the shaped
 * listings do not cover.
 *
 * Keyed on `event_id` and without the `match_id` the archive's own event type
 * carries, because the reviewer is always answering about one match.
 */
export type ReviewMatchEvent = {
  event_id: string;
  timestamp: string;
  actor: string;
  event_type: string;
  action: JsonObject;
  result: JsonObject | null;
};

/**
 * `ReviewStrategyRequest` — body for `POST /api/v1/strategies/review`.
 *
 * Names the strategy to improve and the match to review it against, plus the
 * model and key doing the reviewing. The key travels in the body rather than the
 * query string so it cannot reach a URL, a log or browser history.
 *
 * The answer is streamed and never stored: promoting what comes back is a
 * separate, deliberate `save-strategy`.
 */
export type ReviewStrategyRequest = {
  strategy_id: string;
  match_id: string;
  provider: string;
  model: string;
  api_key: string;
};

/** One Server-Sent Event frame from the strategy-review stream. */
export type ReviewEvent = {
  type:
    | "review_started"
    | "review_tool_call"
    | "review_tool_result"
    | "review_finished"
    | "review_error";
  strategy_id?: string;
  match_id?: string;
  /** `review_tool_call`: the read the agent is making. */
  tool?: string;
  arguments?: JsonObject;
  /** `review_tool_result`: whether that read worked. */
  success?: boolean;
  error?: string | null;
  /** `review_finished`: the proposed strategy. */
  output?: string;
  /** `review_error`: why the review stopped. */
  detail?: string;
};

/**
 * `PublicKeyResponse` — the deployment's key for encrypting api-key fields.
 *
 * `public_key_jwk` is the one a browser uses: WebCrypto's `importKey` takes a
 * JWK as it is, while the PEM would have to be stripped of its armour and
 * base64-decoded to DER first. `algorithm` and `hash_algorithm` are the WebCrypto
 * parameters to import it under. A 503 means the deployment has not configured
 * the transport, and api-key fields are then sent as plaintext, which the server
 * still accepts.
 */
export type PublicKeyResponse = {
  algorithm: string;
  hash_algorithm: string;
  public_key_jwk: JsonObject;
  public_key_pem: string;
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
