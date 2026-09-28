import { formatMatchOutcome } from "@/lib/format";

/** The outcome chip shared by the archive rows and the match masthead. */
export function OutcomeBadge({
  match,
}: {
  match: { winner: string | null; status: string };
}) {
  const { label, muted } = formatMatchOutcome(match);
  return (
    <span className={muted ? "outcome-badge muted" : "outcome-badge"}>
      {label}
    </span>
  );
}
