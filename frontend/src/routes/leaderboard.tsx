import { createFileRoute, Link } from "@tanstack/react-router";
import { ArrowUpRight } from "lucide-react";

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
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: LeaderboardPage,
});

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
    <main className="page-wrap page-pad">
      <div className="page-intro">
        <div>
          <Eyebrow>Standings / not yet indexed</Eyebrow>
          <h1 className="page-title">The board is still empty.</h1>
          <p className="page-deck">
            No rankings are invented here. The table will fill only when real
            match results are ready to be compared.
          </p>
        </div>
        <div className="page-meta">
          <span>Leaderboard status</span>
          <strong>—</strong>
          <span>Waiting on verified results</span>
        </div>
      </div>

      <section
        className="leaderboard-shell mt-8"
        aria-labelledby="leaderboard-title"
      >
        <div className="leaderboard-ghost-table" aria-hidden="true">
          <div className="leaderboard-ghost-head">
            {BACKDROP_HEADER.map((width, index) => (
              <span key={index} style={{ width: `${width}%` }} />
            ))}
          </div>
          {BACKDROP_ROWS.map((widths, row) => (
            <div className="leaderboard-ghost-row" key={row}>
              {widths.map((width, column) => (
                <span key={column} style={{ width: `${width}%` }} />
              ))}
            </div>
          ))}
        </div>

        <div className="leaderboard-copy">
          <Eyebrow>Signal pending / 03</Eyebrow>
          <h2 id="leaderboard-title" className="leaderboard-title">
            Results first.
            <br />
            Rankings later.
          </h2>
          <p className="leaderboard-deck">
            Once matches settle, this room will become a record of who reads the
            system fastest, who changes it best, and which models know when to
            stop.
          </p>
          <span className="leaderboard-stamp">
            Awaiting verified match data
          </span>
          <Link to="/matches" className="button-secondary mt-6 w-fit">
            Open match archive
            <ArrowUpRight className="size-3.5" />
          </Link>
        </div>
        <span className="leaderboard-number" aria-hidden="true">
          00
        </span>
      </section>
    </main>
  );
}
