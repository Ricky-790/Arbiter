import { useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { ArrowUpRight, Search, X } from "lucide-react";
import { useMemo, useState } from "react";

import { Eyebrow } from "@/components/arbiter/app-shell";
import {
  Field,
  FileBlocks,
  JsonBlock,
  TextBlock,
} from "@/components/arbiter/spec-blocks";
import { getChallenge, listChallenges } from "@/lib/api";
import type { ChallengeSchema } from "@/lib/dto";

export const Route = createFileRoute("/challenges")({
  head: () => ({
    meta: [
      {
        name: "description",
        content:
          "Browse deterministic adversarial challenges for Arbiter agents.",
      },
      { property: "og:title", content: "Challenges — Arbiter" },
      {
        property: "og:description",
        content:
          "Browse deterministic adversarial challenges for Arbiter agents.",
      },
      { property: "og:type", content: "website" },
      { property: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: ChallengesPage,
});

function ChallengesPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const challengesQuery = useQuery({
    queryKey: ["challenges"],
    queryFn: listChallenges,
  });

  const detailQuery = useQuery({
    queryKey: ["challenge", selectedId],
    queryFn: () => getChallenge(selectedId ?? ""),
    enabled: selectedId !== null,
  });

  const filtered = useMemo(() => {
    const rows = challengesQuery.data ?? [];
    const needle = query.trim().toLowerCase();
    if (needle === "") return rows;
    return rows.filter(
      (challenge) =>
        challenge.name.toLowerCase().includes(needle) ||
        challenge.description.toLowerCase().includes(needle),
    );
  }, [challengesQuery.data, query]);

  const selectedSummary =
    (challengesQuery.data ?? []).find((row) => row.id === selectedId) ?? null;
  const selected = detailQuery.data ?? null;
  const catalogueSize = challengesQuery.data?.length ?? 0;

  return (
    <main className="page-wrap">
      <section className="page-pad">
        <div className="page-intro">
          <div>
            <Eyebrow>Arena catalogue / 01</Eyebrow>
            <h1 className="page-title">Choose your locked room.</h1>
            <p className="page-deck">
              Each scenario is a fixed puzzle with a measurable exit. Open a
              brief, inspect the files, then put two models inside and see what
              they do under pressure.
            </p>
          </div>
          <div className="page-meta">
            <span>Scenarios indexed</span>
            <strong>{catalogueSize.toString().padStart(2, "0")}</strong>
            <span>Deterministic / sandboxed</span>
          </div>
        </div>

        <div className="toolbar mt-8">
          <span className="mono-label">Filter the catalogue</span>
          <label className="search-box">
            <Search aria-hidden="true" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search by name or brief..."
              aria-label="Search challenges"
            />
          </label>
        </div>

        {challengesQuery.isPending && (
          <p className="loading-line">Reading the arena catalogue...</p>
        )}

        {challengesQuery.isError && (
          <p className="error-line">
            Failed to load challenges:{" "}
            {(challengesQuery.error as Error).message}
          </p>
        )}

        <div className="challenge-list mt-8">
          {filtered.map((challenge, index) => (
            <button
              type="button"
              key={challenge.id}
              onClick={() => setSelectedId(challenge.id)}
              className={`challenge-row ${
                selectedId === challenge.id ? "selected" : ""
              }`}
            >
              <span className="challenge-number">
                {(index + 1).toString().padStart(2, "0")}
              </span>
              <span className="challenge-name">{challenge.name}</span>
              <span className="challenge-description">
                {challenge.description}
              </span>
              <span className="challenge-condition">
                <span className="text-primary">Exit / </span>
                {challenge.win_condition}
              </span>
              <ArrowUpRight className="challenge-arrow size-4" />
            </button>
          ))}
        </div>

        {!challengesQuery.isPending && filtered.length === 0 && (
          <p className="empty-state">No challenge vectors match the query.</p>
        )}
      </section>

      {selectedId !== null && (
        <>
          <button
            type="button"
            className="drawer-backdrop"
            onClick={() => setSelectedId(null)}
            aria-label="Close challenge details"
          />
          <aside
            className="challenge-drawer event-scroll"
            aria-label="Challenge details"
          >
            <div className="drawer-topline">
              <span className="mono-label">Scenario dossier / detail</span>
              <button
                type="button"
                className="drawer-close"
                onClick={() => setSelectedId(null)}
                aria-label="Close challenge details"
              >
                <X className="size-4" />
              </button>
            </div>

            {detailQuery.isPending && (
              <p className="loading-line">Loading full spec...</p>
            )}

            {detailQuery.isError && (
              <p className="error-line">
                Failed to load spec: {(detailQuery.error as Error).message}
              </p>
            )}

            {selected !== null && (
              <ChallengeDetail
                challenge={selected}
                fallbackName={selectedSummary?.name ?? selected.name}
                onLaunch={() =>
                  navigate({
                    to: "/launch",
                    search: { challengeId: selected.id },
                  })
                }
              />
            )}
          </aside>
        </>
      )}
    </main>
  );
}

function ChallengeDetail({
  challenge,
  fallbackName,
  onLaunch,
}: {
  challenge: ChallengeSchema;
  fallbackName: string;
  onLaunch: () => void;
}) {
  const fileEntries = Object.entries(challenge.files);
  const envEntries = Object.entries(challenge.env_vars);

  return (
    <>
      <h2 className="drawer-title">{challenge.name || fallbackName}</h2>
      <p className="drawer-type">
        Type / <strong>{challenge.challenge_type}</strong>
      </p>

      <Field label="WIN_CONDITION">
        <p>{challenge.win_condition}</p>
      </Field>

      <Field label="DESCRIPTION">
        <p className="text-muted-foreground">{challenge.description}</p>
      </Field>

      <Field label="FLAG_STRUCTURE">
        <JsonBlock value={challenge.flag_structure} />
      </Field>

      <Field label="EXPECTED_FLAG (ANSWER)">
        <JsonBlock value={challenge.flag} />
      </Field>

      <Field label={`FILES (${fileEntries.length})`}>
        <FileBlocks files={challenge.files} />
      </Field>

      <Field label={`ENV_VARS (${envEntries.length})`}>
        <JsonBlock value={challenge.env_vars} />
      </Field>

      <Field label="SANDBOX_CONFIG">
        <JsonBlock value={challenge.sandbox_config} />
      </Field>

      <Field label="SETUP_SCRIPT">
        <TextBlock value={challenge.setup_script} />
      </Field>

      <Field label="VERIFIER_SCRIPT">
        <TextBlock value={challenge.verifier_script} />
      </Field>

      <Field label="TIMESTAMPS">
        <div className="space-y-1 font-mono text-xs text-muted-foreground">
          <div>Created: {formatTimestamp(challenge.created_at)}</div>
          <div>Updated: {formatTimestamp(challenge.updated_at)}</div>
        </div>
      </Field>

      <button
        type="button"
        onClick={onLaunch}
        className="button-primary mt-8 w-full"
      >
        Launch this match
        <ArrowUpRight className="size-3.5" />
      </button>
    </>
  );
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}
