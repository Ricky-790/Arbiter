import { createFileRoute } from "@tanstack/react-router";

import { StrategyView } from "@/components/arbiter/strategy-view";

/**
 * `/strategy?strategy_id=<strategyId>` — one saved strategy: its wording, the
 * match it was promoted from, and the matches started from it since.
 */
export const Route = createFileRoute("/strategy")({
  validateSearch: (
    search: Record<string, unknown>,
  ): { strategy_id?: string } => {
    const strategyId = search["strategy_id"];
    return typeof strategyId === "string" && strategyId !== ""
      ? { strategy_id: strategyId }
      : {};
  },
  head: () => ({
    meta: [
      {
        name: "description",
        content:
          "One saved Arbiter strategy: the wording, the match it came from, and where it has been used.",
      },
      { property: "og:title", content: "Strategy — Arbiter" },
      {
        property: "og:description",
        content: "A saved strategy's wording and the matches that have run it.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: StrategyPage,
});

function StrategyPage() {
  const { strategy_id: strategyId } = Route.useSearch();

  if (strategyId === undefined) {
    return (
      <main className="page-wrap page-pad">
        <div className="page-intro">
          <div>
            <p className="eyebrow">Strategy</p>
            <h1 className="page-title">Pick a strategy.</h1>
            <p className="page-deck">
              Open one from the archive to read its wording and see which
              matches have been started from it.
            </p>
          </div>
        </div>
      </main>
    );
  }

  return <StrategyView strategyId={strategyId} />;
}
