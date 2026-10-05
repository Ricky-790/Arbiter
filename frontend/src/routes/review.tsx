import { createFileRoute } from "@tanstack/react-router";

import { ReviewWorkbench } from "@/components/arbiter/review-workbench";

/**
 * `/review?strategy_id=…&match_id=…` — one strategy against one match.
 *
 * The strategy names the side, so the two ids are enough: the page shows only
 * that side's stats, conversation, tool calls and narration for that one match,
 * and can run the reviewer over exactly what is on screen.
 */
export const Route = createFileRoute("/review")({
  validateSearch: (
    search: Record<string, unknown>,
  ): { strategy_id?: string; match_id?: string } => {
    const read = (key: string): string | undefined => {
      const value = search[key];
      return typeof value === "string" && value !== "" ? value : undefined;
    };
    const strategyId = read("strategy_id");
    const matchId = read("match_id");
    return {
      ...(strategyId === undefined ? {} : { strategy_id: strategyId }),
      ...(matchId === undefined ? {} : { match_id: matchId }),
    };
  },
  head: () => ({
    meta: [
      {
        name: "description",
        content:
          "One Arbiter strategy reviewed against one match: that side's stats, conversation and tool calls, plus an AI proposal.",
      },
      { property: "og:title", content: "Strategy Review — Arbiter" },
      {
        property: "og:description",
        content:
          "A strategy's match record, read side by side, with an AI review proposing a better approach.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: ReviewPage,
});

function ReviewPage() {
  const { strategy_id: strategyId, match_id: matchId } = Route.useSearch();

  if (strategyId === undefined || matchId === undefined) {
    return (
      <main className="page-wrap page-pad">
        <div className="page-intro">
          <div>
            <p className="eyebrow">Review</p>
            <h1 className="page-title">Pick a match to review.</h1>
            <p className="page-deck">
              Open a strategy from the archive, then choose Review on the match
              you want it judged against.
            </p>
          </div>
        </div>
      </main>
    );
  }

  return <ReviewWorkbench strategyId={strategyId} matchId={matchId} />;
}
