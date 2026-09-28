/**
 * Reading helpers for a match's persisted event history.
 *
 * The two actor panels are built from the same flat event list, so the
 * ordering, partitioning and turn grouping all live here rather than in the
 * view that happens to render them.
 */

import type { JsonObject, MatchEventSchema } from "./dto";

/** The persisted tool-call `action` fields the grouping rule cares about. */
type ToolCallAction = JsonObject & {
  batch_id?: unknown;
};

/** One forkable step in an actor's history: a tool-call batch, or one event. */
export type EventGroup = {
  /** Stable key for React and for the group bracket. */
  key: string;
  /** The shared `action.batch_id`, or null for a single ungrouped event. */
  batchId: string | null;
  /** Members in chronological order. */
  events: MatchEventSchema[];
  /**
   * The event the fork request should name.
   *
   * The backend snaps any member of a batch forward to the batch's last call
   * (`snap_branch_event` in `backend/app/engine/resumability.py`), because
   * pydantic-ai returns one response's tool results in a single message and no
   * conversation state exists between them. Sending the last member keeps the
   * request honest about what will actually be restored.
   */
  forkEventId: string;
  startTime: string;
  endTime: string;
};

/** Sort key for an event; unparseable or missing timestamps sort first. */
export function eventTime(event: MatchEventSchema): number {
  const parsed = new Date(event.timestamp).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** Wall-clock time of a persisted event, or a dash when unparseable. */
export function formatEventTime(timestamp: string): string {
  const parsed = new Date(timestamp);
  if (Number.isNaN(parsed.getTime())) return "--:--:--";
  return parsed.toLocaleTimeString([], { hour12: false });
}

/** Whether an event belongs to the match rather than to one agent. */
export function isSystemEvent(event: MatchEventSchema): boolean {
  return event.actor !== "prisoner" && event.actor !== "warden";
}

/**
 * One actor's timeline: its own events plus the match-wide ones, oldest first.
 *
 * System events are intentionally present in both panels, so each column reads
 * as a complete timeline of the match.
 */
export function eventsForActor(
  events: MatchEventSchema[],
  actor: string,
): MatchEventSchema[] {
  return events
    .filter((event) => event.actor === actor || isSystemEvent(event))
    .sort((a, b) => eventTime(a) - eventTime(b));
}

/** The batch a tool call was emitted in, when the backend tracked one. */
export function toolCallBatchId(event: MatchEventSchema): string | null {
  if (event.event_type !== "tool_call") return null;
  const { batch_id: batchId } = event.action as ToolCallAction;
  return typeof batchId === "string" && batchId !== "" ? batchId : null;
}

/**
 * Collapse tool calls emitted in the same model response into one turn.
 *
 * Grouping is by batch id rather than by adjacency: the sandbox monitor
 * persists its `sandbox_event` rows asynchronously, so one can land between two
 * calls of the same batch and a "consecutive" rule would split a single turn in
 * two. Groups keep the position of their first member and pull later members up
 * into it, which is why a group's header prints its time span.
 *
 * Events with no batch id — older matches, and every non-tool-call event — fall
 * back to a one-event group, so every step in the timeline stays forkable.
 */
export function groupEventsByBatch(events: MatchEventSchema[]): EventGroup[] {
  const seen = new Map<
    string,
    { first: MatchEventSchema; group: EventGroup }
  >();
  const ordered: EventGroup[] = [];

  for (const event of events) {
    const batchId = toolCallBatchId(event);
    const key = batchId === null ? `event:${event.id}` : `batch:${batchId}`;
    const existing = seen.get(key);

    if (existing === undefined) {
      const group: EventGroup = {
        key,
        batchId,
        events: [event],
        forkEventId: event.id,
        startTime: event.timestamp,
        endTime: event.timestamp,
      };
      seen.set(key, { first: event, group });
      ordered.push(group);
      continue;
    }

    existing.group.events.push(event);
    if (isAfter(event, existing.first)) {
      existing.group.forkEventId = event.id;
      existing.group.endTime = event.timestamp;
    }
    if (eventTime(event) < eventTime(existing.first)) {
      existing.group.startTime = event.timestamp;
    }
  }

  return ordered;
}

/** Whether `event` sorts after `reference` on (timestamp, id). */
function isAfter(
  event: MatchEventSchema,
  reference: MatchEventSchema,
): boolean {
  const delta = eventTime(event) - eventTime(reference);
  if (delta !== 0) return delta > 0;
  return event.id > reference.id;
}
