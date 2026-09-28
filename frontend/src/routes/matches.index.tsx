import { createFileRoute } from "@tanstack/react-router";

import { MatchArchive } from "@/components/arbiter/match-archive";
import { MatchView } from "@/components/arbiter/match-view";

/**
 * `/matches` shows the archive; `/matches?match_id=<matchId>` shows one match.
 *
 * `MatchView` reads the match row and renders the live room, the preparing
 * gate, or the recorded transcript, so the finished/live decision never has to
 * be baked into a link. `id` is still accepted so links from before the rename
 * keep resolving onto the same view.
 */
export const Route = createFileRoute("/matches/")({
  validateSearch: (search: Record<string, unknown>): { match_id?: string } => {
    const value = search["match_id"] ?? search["id"];
    return typeof value === "string" && value !== "" ? { match_id: value } : {};
  },
  head: () => ({
    meta: [
      {
        name: "description",
        content: "Review completed and active agent-vs-agent matches.",
      },
      { property: "og:title", content: "Matches — Arbiter" },
      {
        property: "og:description",
        content: "Review completed and active agent-vs-agent matches.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: MatchesPage,
});

function MatchesPage() {
  const { match_id: matchId } = Route.useSearch();
  return matchId === undefined ? (
    <MatchArchive />
  ) : (
    <MatchView matchId={matchId} />
  );
}
