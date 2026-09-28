import { useMemo } from "react";
import { MessageSquareQuote } from "lucide-react";

import { readConversation } from "@/lib/agent-messages";
import {
  EventGroup,
  type DescribedLine,
} from "@/components/arbiter/event-group";
import type { MatchEventSchema } from "@/lib/dto";
import { formatArguments } from "@/lib/format";
import { groupEventsByBatch } from "@/lib/match-events";

/**
 * What a saved fork carries: the conversation each agent already had, and the
 * turns that were replayed to reach this point. This is the read-only half of
 * the fork page — the seat pickers and the start button sit below it in
 * `ForkWorkbench`.
 */
export function ForkMemory({
  turns,
  prisonerMessages,
  wardenMessages,
}: {
  turns: MatchEventSchema[];
  prisonerMessages: Record<string, unknown>[] | null;
  wardenMessages: Record<string, unknown>[] | null;
}) {
  const prisonerConversation = useMemo(
    () => readConversation(prisonerMessages),
    [prisonerMessages],
  );
  const wardenConversation = useMemo(
    () => readConversation(wardenMessages),
    [wardenMessages],
  );

  return (
    <>
      <div className="fork-memory">
        <Conversation
          title="Prisoner"
          subtitle="What the attacker already knows"
          tone="prisoner"
          lines={prisonerConversation}
        />
        <Conversation
          title="Warden"
          subtitle="What the defender already knows"
          tone="warden"
          lines={wardenConversation}
        />
      </div>

      <div className="fork-turns">
        <div className="agent-heading">
          <h2>Latest moves</h2>
          <span className="mono-label">
            {turns.length} {turns.length === 1 ? "step" : "steps"} replayed to
            reach this point
          </span>
        </div>
        {turns.length === 0 ? (
          <p className="event-empty">
            This fork was taken before any tool ran.
          </p>
        ) : (
          groupEventsByBatch(turns).map((group) => (
            <EventGroup
              key={group.key}
              group={group}
              describe={describeForkTurn}
              forkable={false}
              selected={false}
              forking={false}
            />
          ))
        )}
      </div>
    </>
  );
}

function Conversation({
  title,
  subtitle,
  tone,
  lines,
}: {
  title: string;
  subtitle: string;
  tone: "prisoner" | "warden";
  lines: ReturnType<typeof readConversation>;
}) {
  return (
    <section className={`fork-conversation ${tone}`}>
      <header className="fork-conversation-head">
        <span className="event-panel-name">{title}</span>
        <span className="event-panel-role">{subtitle}</span>
      </header>
      {lines.length === 0 ? (
        <p className="event-empty">
          <MessageSquareQuote className="mr-2 inline size-3.5" />
          No stored conversation at this point.
        </p>
      ) : (
        <div className="fork-conversation-body">
          {lines.map((line, index) => (
            <p
              className={`fork-line is-${line.role}`}
              key={`${line.role}-${index}`}
            >
              {line.text}
            </p>
          ))}
        </div>
      )}
    </section>
  );
}

/** A replayed tool call, described the way the transcript describes it. */
function describeForkTurn(event: MatchEventSchema): DescribedLine {
  const tool =
    typeof event.action["tool"] === "string" ? event.action["tool"] : "unknown";
  const args = formatArguments(event.action["arguments"]);
  const success = event.result?.["success"] === true;
  return {
    text: `${tool}${args === "" ? "" : ` (${args})`} -> ${success ? "OK" : "FAIL"}`,
    tone: "default",
    label: { text: "TOOL", tone: success ? "success" : "failure" },
    detail: null,
  };
}
