import { useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Search, X } from "lucide-react";
import { useMemo, useState } from "react";

import { Eyebrow } from "@/components/arbiter/app-shell";
import {
  Field,
  FileBlocks,
  JsonBlock,
  TextBlock,
} from "@/components/arbiter/spec-blocks";
import { Button } from "@/components/ui/button";
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

  return (
    <main>
      <div className="border-b border-border bg-panel px-5 py-3 lg:px-8">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center gap-2">
          <label className="relative ml-auto min-w-[250px]">
            <Search className="absolute left-3 top-2.5 size-3.5 text-muted-foreground" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search challenge..."
              className="h-9 w-full border border-border bg-background pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground"
            />
          </label>
        </div>
      </div>

      <div className="mx-auto max-w-[1600px]">
        <section className="min-h-[calc(100vh-109px)] px-5 py-8 lg:px-8">
          <h1 className="mt-3 font-display text-3xl font-bold">
            Available Scenarios
          </h1>

          {challengesQuery.isPending && (
            <p className="mt-10 text-sm text-muted-foreground">
              LOADING CHALLENGE...
            </p>
          )}

          {challengesQuery.isError && (
            <p className="mt-10 text-sm text-destructive">
              FAILED TO LOAD CHALLENGES:{" "}
              {(challengesQuery.error as Error).message}
            </p>
          )}

          <div className="mt-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {filtered.map((challenge) => (
              <button
                key={challenge.id}
                onClick={() => setSelectedId(challenge.id)}
                className={`data-panel min-h-52 cursor-pointer p-4 text-left transition-colors hover:border-primary focus-visible:outline focus-visible:outline-1 focus-visible:outline-primary ${
                  selectedId === challenge.id ? "border-primary" : ""
                }`}
              >
                <h2 className="text-base font-bold">{challenge.name}</h2>
                <p className="mt-2 text-sm leading-5 text-muted-foreground">
                  {challenge.description}
                </p>
                <p className="mt-4 text-sm leading-5 text-primary">
                  {challenge.win_condition}
                </p>
              </button>
            ))}
          </div>

          {!challengesQuery.isPending && filtered.length === 0 && (
            <p className="mt-10 text-sm text-muted-foreground">
              NO CHALLENGE VECTORS MATCH THE QUERY.
            </p>
          )}
        </section>

        {selectedId !== null && (
          <>
            <button
              type="button"
              className="fixed inset-0 z-40 bg-background/70"
              onClick={() => setSelectedId(null)}
              aria-label="Close challenge details"
            />
            <aside
              className="drawer-in event-scroll fixed inset-y-0 right-0 z-50 w-full max-w-xl overflow-y-auto border-l border-border bg-panel p-7 shadow-2xl"
              aria-label="Challenge details"
            >
              {/*<div className="flex items-center">*/}
              <div className="flex justify-end">
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setSelectedId(null)}
                  className=" size-8 rounded-none py-2"
                  aria-label="Close challenge details"
                >
                  <X className="size-4" />
                </Button>
              </div>

              {detailQuery.isPending && (
                <p className="mt-6 text-sm text-muted-foreground">
                  LOADING FULL SPEC...
                </p>
              )}

              {detailQuery.isError && (
                <p className="mt-6 text-sm text-destructive">
                  FAILED TO LOAD SPEC: {(detailQuery.error as Error).message}
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
      </div>
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
      <h2 className="mt-6 break-words font-display text-3xl font-bold">
        {challenge.name || fallbackName}
      </h2>
      <div className="mt-3 border-b border-border pb-5 text-sm text-muted-foreground">
        TYPE: <span className="text-primary">{challenge.challenge_type}</span>
      </div>

      <Field label="WIN_CONDITION">
        <p className="text-base leading-6 text-foreground">
          {challenge.win_condition}
        </p>
      </Field>

      <Field label="DESCRIPTION">
        <p className="text-base leading-6 text-muted-foreground">
          {challenge.description}
        </p>
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
        <div className="space-y-1 text-sm text-muted-foreground">
          <div>CREATED: {formatTimestamp(challenge.created_at)}</div>
          <div>UPDATED: {formatTimestamp(challenge.updated_at)}</div>
        </div>
      </Field>

      <Button
        onClick={onLaunch}
        className="mt-7 h-12 w-full rounded-none font-mono text-base font-bold"
      >
        LAUNCH MATCH
      </Button>
    </>
  );
}

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}
