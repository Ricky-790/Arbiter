import { GitBranch } from "lucide-react";

import { LogLine, type LogTone } from "@/components/arbiter/log-line";
import type { MatchEventSchema } from "@/lib/dto";
import {
  formatEventTime,
  type EventGroup as EventGroupModel,
} from "@/lib/match-events";

/** How one persisted event row is presented, resolved by the owning view. */
export type DescribedLine = {
  text: string;
  tone: LogTone;
  label: { text: string; tone: LogTone } | null;
  detail: Record<string, unknown> | null;
};

/**
 * One forkable step of an actor's history.
 *
 * A group is either the tool calls one model response emitted together (they
 * share `action.batch_id`) or a single ungrouped event. A turn gets a labelled
 * header and its own bracket; a lone event stays quiet and only grows a fork
 * control on hover. Either way each member is still an ordinary `LogLine` with
 * its own timestamp and expandable result.
 */
export function EventGroup({
  group,
  describe,
  forkable,
  forkBlockedReason,
  selected,
  forking,
  onFork,
}: {
  group: EventGroupModel;
  describe: (event: MatchEventSchema) => DescribedLine;
  forkable: boolean;
  /** Why forking is unavailable, shown on the disabled control. */
  forkBlockedReason?: string;
  selected: boolean;
  forking: boolean;
  /** Omitted where turns are shown for reading only, e.g. a fork's history. */
  onFork?: (group: EventGroupModel) => void;
}) {
  const isTurn = group.batchId !== null || group.events.length > 1;
  const callCount = group.events.length;
  const span =
    group.startTime !== group.endTime
      ? `${formatEventTime(group.startTime)}–${formatEventTime(group.endTime)}`
      : formatEventTime(group.endTime);

  const forkControl =
    onFork === undefined ? null : (
      <button
        type="button"
        className="event-group-fork"
        disabled={!forkable || forking}
        title={forkable ? undefined : forkBlockedReason}
        onClick={() => onFork(group)}
      >
        <GitBranch className="size-3" />
        {isTurn ? "Fork after turn" : "Fork here"}
      </button>
    );

  return (
    <div className={`event-group ${selected ? "is-selected" : ""}`}>
      {isTurn && (
        <div className="event-group-head">
          <span className="event-group-index">Turn</span>
          <span className="event-group-label">
            {callCount} {callCount === 1 ? "call" : "calls"}
          </span>
          <span className="event-group-time">{span}</span>
          {onFork !== undefined && (
            <span className="event-group-note">
              fork continues after this group
            </span>
          )}
          {forkControl}
        </div>
      )}

      <div className="event-group-body">
        {group.events.map((event, index) => {
          const line = describe(event);
          return (
            <div className="event-group-row" key={event.id}>
              {!isTurn && index === group.events.length - 1 && forkControl}{" "}
              <LogLine
                time={formatEventTime(event.timestamp)}
                text={line.text}
                tone={line.tone}
                label={line.label}
                detail={line.detail}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
