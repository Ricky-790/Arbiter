/** Display helpers shared by the match views. */

/**
 * Flatten a tool call's arguments into a single readable string, e.g.
 * `{ "command": "ls -ls ./" }` becomes `command=ls -ls ./`.
 */
export function formatArguments(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value !== "object") return String(value);
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return "";
  return entries
    .map(([key, entry]) => `${key}=${shortValue(entry)}`)
    .join(", ");
}

function shortValue(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return String(value);
  try {
    return JSON.stringify(value) ?? String(value);
  } catch {
    return String(value);
  }
}

/** `provider/model`, or just the model when the provider is unknown. */
export function formatModel(provider: string, model: string): string {
  return provider === "" ? model : `${provider}/${model}`;
}

/** A match duration in `mm:ss`. */
export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const remainder = total % 60;
  return `${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}`;
}

/** A local date-time string, falling back to the raw value when unparseable. */
export function formatDateTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/** The archive badge for a match outcome. */
export function formatMatchOutcome(match: {
  winner: string | null;
  status: string;
}): { label: string; muted: boolean } {
  switch (match.winner) {
    case "prisoner":
      return { label: "PRISONER WIN", muted: false };
    case "warden":
      return { label: "WARDEN WIN", muted: false };
    case "draw":
      return { label: "DRAW", muted: true };
    default:
      return { label: match.status.toUpperCase(), muted: true };
  }
}
