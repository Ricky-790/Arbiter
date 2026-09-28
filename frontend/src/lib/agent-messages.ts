/**
 * Reading pydantic-ai conversations.
 *
 * A saved fork stores each agent's conversation as the JSON dump
 * `ModelMessagesTypeAdapter.dump_python` produces (`dump_agent_history` in
 * `backend/app/agents/base.py`), so a message is `{kind, parts, timestamp}` and
 * a part is discriminated by `part_kind`. Those are internal shapes, so this
 * reads them defensively: anything unrecognised is skipped rather than
 * rendered as raw JSON, and a conversation from an older row that predates
 * message storage is simply empty.
 */

import type { JsonObject } from "./dto";

/** Who a line of conversation came from. */
export type ConversationRole = "agent" | "user" | "tool" | "system";

/** One displayable line of an agent's stored conversation. */
export type ConversationLine = {
  role: ConversationRole;
  text: string;
};

const MAX_TEXT = 400;

/**
 * Flatten a dumped conversation into the lines worth showing.
 *
 * `limit` keeps the most recent lines, since a resumed conversation is read for
 * what the agent is about to remember, not for how it got there.
 */
export function readConversation(
  messages: JsonObject[] | null | undefined,
  limit = 12,
): ConversationLine[] {
  if (messages === null || messages === undefined) return [];
  const lines: ConversationLine[] = [];

  for (const message of messages) {
    if (message === null || typeof message !== "object") continue;
    const parts = message["parts"];
    if (!Array.isArray(parts)) continue;

    for (const raw of parts) {
      if (raw === null || typeof raw !== "object") continue;
      const part = raw as JsonObject;
      const kind = part["part_kind"];
      const content = part["content"];

      if (kind === "text" || kind === "thinking") {
        pushLine(lines, "agent", textOf(content));
        continue;
      }
      if (kind === "user-prompt" || kind === "retry-prompt") {
        pushLine(lines, "user", textOf(content));
        continue;
      }
      if (kind === "tool-return") {
        const name =
          typeof part["tool_name"] === "string" ? part["tool_name"] : "tool";
        pushLine(lines, "tool", `${name} returned ${textOf(content)}`);
      }
    }
  }

  return lines.length <= limit ? lines : lines.slice(-limit);
}

function pushLine(
  lines: ConversationLine[],
  role: ConversationRole,
  text: string,
): void {
  const trimmed = text.trim();
  if (trimmed === "") return;
  lines.push({
    role,
    text:
      trimmed.length > MAX_TEXT ? `${trimmed.slice(0, MAX_TEXT)}…` : trimmed,
  });
}

/** Pull a displayable string out of a part's `content`, which may be structured. */
function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .map((item) => {
        if (typeof item === "string") return item;
        if (item !== null && typeof item === "object") {
          const nested = (item as JsonObject)["content"];
          if (typeof nested === "string") return nested;
        }
        return "";
      })
      .filter((part) => part !== "")
      .join(" ");
  }
  if (content === null || content === undefined) return "";
  try {
    return JSON.stringify(content);
  } catch {
    return "";
  }
}
