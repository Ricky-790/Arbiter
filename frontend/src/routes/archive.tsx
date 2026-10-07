import { createFileRoute } from "@tanstack/react-router";

import { Eyebrow } from "@/components/arbiter/app-shell";
import { ForkList } from "@/components/arbiter/fork-list";
import { ForkWorkbench } from "@/components/arbiter/fork-workbench";
import { StrategyList } from "@/components/arbiter/strategy-list";

/**
 * `/archive` — everything worth keeping from matches that have been run, in two
 * sections: the strategy library above, the saved fork points below.
 *
 * Strategies and forks are the two halves of the same loop. A strategy is one
 * side's approach, promoted out of a finished match and reusable on the next
 * one; a fork is a whole position — sandbox and both conversations — captured at
 * one moment. Neither is a match, so neither appears in the match archive.
 *
 * `?fork_id=<forkId>` opens one fork to run as a new match.
 */
export const Route = createFileRoute("/archive")({
  validateSearch: (search: Record<string, unknown>): { fork_id?: string } => {
    const forkId = search["fork_id"];
    return typeof forkId === "string" && forkId !== ""
      ? { fork_id: forkId }
      : {};
  },
  head: () => ({
    meta: [
      {
        name: "description",
        content:
          "Arbiter's saved strategies and fork points: every approach promoted out of a finished match, and every position worth re-running.",
      },
      { property: "og:title", content: "Archive — Arbiter" },
      {
        property: "og:description",
        content:
          "Saved strategies and fork points, promoted and captured from finished Arbiter matches.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: ArchivePage,
});

function ArchivePage() {
  const { fork_id: forkId } = Route.useSearch();
  if (forkId !== undefined) return <ForkWorkbench forkId={forkId} />;

  return (
    <main className="page-wrap page-pad">
      <div className="page-intro">
        <div>
          <Eyebrow>Archive / strategies and forks</Eyebrow>
          <h1 className="page-title">
            Public archive of saved strategies / fork points
          </h1>
          <p className="page-deck">
            Strategies are the approaches worth keeping — one agent&apos;s
            wording, promoted out of the match that produced it. Forks are whole
            positions, captured mid-match with the sandbox and both
            conversations intact, ready to run again with different models.
          </p>
        </div>
      </div>

      <StrategyList />

      <ForkList />
    </main>
  );
}
