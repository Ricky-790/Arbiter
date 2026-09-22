import { createFileRoute } from "@tanstack/react-router";

import { MatchArchive } from "@/components/arbiter/match-archive";
import { MatchDetails } from "@/components/arbiter/match-details";

/**
 * `/matches` shows the archive, and `/matches?id=<matchId>` shows one match's
 * recorded details. `id` is optional so a bare `/matches` never redirects.
 */
export const Route = createFileRoute("/matches/")({
  validateSearch: (search: Record<string, unknown>): { id?: string } => {
    const id = search["id"];
    return typeof id === "string" && id !== "" ? { id } : {};
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
      { property: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: MatchesPage,
});

function MatchesPage() {
  const { id } = Route.useSearch();
  return id === undefined ? <MatchArchive /> : <MatchDetails matchId={id} />;
}
