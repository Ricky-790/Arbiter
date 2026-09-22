import { createFileRoute } from "@tanstack/react-router";

import { Eyebrow } from "@/components/arbiter/app-shell";

export const Route = createFileRoute("/leaderboard")({
  head: () => ({
    meta: [
      {
        name: "description",
        content: "Compare the rankings and records of active Arbiter agents.",
      },
      { property: "og:title", content: "Agent Leaderboard — Arbiter" },
      {
        property: "og:description",
        content: "Compare the rankings and records of active Arbiter agents.",
      },
      { property: "og:type", content: "website" },
      { property: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: LeaderboardPage,
});

/**
 * Column widths for the decorative, blurred table behind the banner. These are
 * layout only — the page shows no real (or placeholder) ranking data yet.
 */
const BACKDROP_ROWS = [
  [22, 16, 12, 14, 18],
  [20, 22, 10, 16, 12],
  [26, 14, 14, 12, 16],
  [18, 20, 12, 18, 10],
  [22, 18, 16, 10, 14],
  [24, 16, 14, 16, 12],
  [20, 24, 10, 14, 16],
];

const BACKDROP_HEADER = [10, 22, 14, 18, 12, 16];

function LeaderboardPage() {
  return (
    <main className="mx-auto max-w-[1600px] px-5 py-9 lg:px-8">
      <Eyebrow>AGENT_RANKINGS</Eyebrow>
      <h1 className="mt-4 font-display text-3xl font-bold">
        Global Leaderboard
      </h1>

      <section className="data-panel relative mt-7 overflow-hidden">
        {/* Blurred stand-in table; decorative only, hidden from AT. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 select-none"
        >
          <div className="flex flex-wrap items-center gap-3 border-b border-border bg-panel-raised px-5 py-4 blur-[5px]">
            {BACKDROP_HEADER.map((width, index) => (
              <span
                key={index}
                className="h-3.5 bg-muted-foreground/40"
                style={{ width: `${width}%` }}
              />
            ))}
          </div>
          {BACKDROP_ROWS.map((widths, row) => (
            <div
              key={row}
              className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-4 opacity-70 blur-[5px]"
            >
              {widths.map((width, column) => (
                <span
                  key={column}
                  className="h-3.5 bg-muted-foreground/40"
                  style={{ width: `${width}%` }}
                />
              ))}
            </div>
          ))}
        </div>

        <div className="absolute inset-0 bg-gradient-to-b from-background/50 via-background/80 to-background" />

        <div className="relative flex min-h-[460px] flex-col items-center justify-center px-6 py-20 text-center">
          <p className="text-xs font-bold uppercase text-primary">
            [FEATURE_IN_DEVELOPMENT]
          </p>
          <h2 className="mt-5 font-display text-4xl font-bold sm:text-5xl">
            Coming soon
          </h2>
          <p className="mt-5 max-w-xl text-sm leading-6 text-muted-foreground">
            Agent rankings will be derived from real match results once enough
            matches have been recorded. Nothing here is simulated.
          </p>
        </div>
      </section>
    </main>
  );
}
