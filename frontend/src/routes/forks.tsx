import { createFileRoute } from "@tanstack/react-router";

import { ForkList } from "@/components/arbiter/fork-list";
import { ForkWorkbench } from "@/components/arbiter/fork-workbench";

/**
 * `/forks` lists every saved fork point; `/forks?fork_id=<forkId>` opens one
 * to run as a new match.
 *
 * A fork is a checkpoint on a finished match rather than a match of its own, so
 * it never appears in the match archive and never has its own live stream.
 */
export const Route = createFileRoute("/forks")({
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
        content: "Re-run a finished Arbiter match from a saved fork point.",
      },
      { property: "og:title", content: "Forks — Arbiter" },
      {
        property: "og:description",
        content: "Re-run a finished Arbiter match from a saved fork point.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: ForksPage,
});

function ForksPage() {
  const { fork_id: forkId } = Route.useSearch();
  return forkId === undefined ? (
    <ForkList />
  ) : (
    <ForkWorkbench forkId={forkId} />
  );
}
