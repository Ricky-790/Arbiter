import { createFileRoute, redirect } from "@tanstack/react-router";

/**
 * Legacy live-match URL.
 *
 * The live spectate page used to live at `/matches/:matchId` and took the
 * prisoner, warden and challenge names as query hints. It is now the single
 * `/matches?match_id=...` view, which reads the match row for those names
 * instead, so old bookmarks and shared links are redirected rather than kept
 * alive as a second copy of the page.
 */
export const Route = createFileRoute("/matches/$matchId")({
  beforeLoad: ({ params }) => {
    throw redirect({
      to: "/matches",
      search: { match_id: params.matchId },
    });
  },
  head: () => ({
    meta: [
      {
        name: "description",
        content:
          "Watch Prisoner and Warden agents act inside an Arbiter sandbox.",
      },
      { property: "og:title", content: "Spectate Match — Arbiter" },
      {
        property: "og:description",
        content:
          "Watch Prisoner and Warden agents act inside an Arbiter sandbox.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
});
