import { useMutation, useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { Eyebrow } from "@/components/arbiter/app-shell";
import { Button } from "@/components/ui/button";
import { getChallenge, listFreeModels, startMatch } from "@/lib/api";

export const Route = createFileRoute("/launch")({
  validateSearch: (
    search: Record<string, unknown>,
  ): { challengeId?: string } => {
    const challengeId = search["challengeId"];
    return typeof challengeId === "string" ? { challengeId } : {};
  },
  head: () => ({
    meta: [
      {
        name: "description",
        content: "Pick the Prisoner and Warden models for a new Arbiter match.",
      },
      { property: "og:title", content: "Launch Match — Arbiter" },
      {
        property: "og:description",
        content: "Pick the Prisoner and Warden models for a new Arbiter match.",
      },
      { property: "og:type", content: "website" },
      { property: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: LaunchPage,
});

function LaunchPage() {
  const navigate = useNavigate();
  const { challengeId = "" } = Route.useSearch();
  const [prisonerModel, setPrisonerModel] = useState("");
  const [wardenModel, setWardenModel] = useState("");
  const [prisonerSuggestions, setPrisonerSuggestions] = useState("");
  const [wardenSuggestions, setWardenSuggestions] = useState("");

  const modelsQuery = useQuery({
    queryKey: ["free-models"],
    queryFn: listFreeModels,
  });

  const challengeQuery = useQuery({
    queryKey: ["challenge", challengeId],
    queryFn: () => getChallenge(challengeId),
    enabled: challengeId !== "",
  });

  const launch = useMutation({
    mutationFn: () =>
      startMatch({
        challenge_id: challengeId,
        prisoner_model: prisonerModel,
        warden_model: wardenModel,
        prisoner_suggestions: prisonerSuggestions.trim() || null,
        warden_suggestions: wardenSuggestions.trim() || null,
      }),
    onSuccess: (response) => {
      navigate({
        to: "/matches/$matchId",
        params: { matchId: response.match_id },
        search: {
          prisoner: prisonerModel,
          warden: wardenModel,
          challenge: challengeQuery.data?.name ?? "",
        },
      });
    },
  });

  const models = modelsQuery.data ?? [];
  const challenge = challengeQuery.data ?? null;
  const ready =
    challengeId !== "" &&
    prisonerModel !== "" &&
    wardenModel !== "" &&
    prisonerModel !== wardenModel &&
    !launch.isPending;

  if (challengeId === "") {
    return (
      <main className="mx-auto max-w-3xl px-5 py-16 lg:px-8">
        <Eyebrow>LAUNCH_MATCH</Eyebrow>
        <h1 className="mt-4 font-display text-3xl font-bold">
          No challenge selected
        </h1>
        <p className="mt-3 text-sm text-muted-foreground">
          Open a challenge from the repository and press LAUNCH ADVERSARIAL
          MATCH.
        </p>
        <Button asChild className="mt-7 rounded-none">
          <Link to="/challenges">BACK TO CHALLENGES</Link>
        </Button>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-5 py-12 lg:px-8">
      <Eyebrow>LAUNCH_MATCH</Eyebrow>
      <h1 className="mt-4 font-display text-3xl font-bold">
        Configure Adversaries
      </h1>
      <p className="mt-3 text-sm text-muted-foreground">
        Choose one model per side. The same model cannot play both roles.
      </p>

      <div className="data-panel mt-7 p-5">
        <h2 className="text-[11px] text-muted-foreground">
          // TARGET_CHALLENGE
        </h2>
        {challengeQuery.isPending && (
          <p className="mt-3 text-sm text-muted-foreground">LOADING...</p>
        )}
        {challengeQuery.isError && (
          <p className="mt-3 text-sm text-destructive">
            FAILED TO LOAD CHALLENGE: {(challengeQuery.error as Error).message}
          </p>
        )}
        {challenge !== null && (
          <div className="mt-3">
            <div className="text-sm font-bold">{challenge.name}</div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {challenge.description}
            </p>
            <p className="mt-3 text-[11px] text-primary">
              WIN: {challenge.win_condition}
            </p>
          </div>
        )}
      </div>

      <div className="mt-5 grid gap-5 sm:grid-cols-2">
        <ModelSelect
          label="PRISONER"
          hint="OFFENSIVE AGENT"
          value={prisonerModel}
          onChange={setPrisonerModel}
          models={models.filter((model) => model !== wardenModel)}
          loading={modelsQuery.isPending}
          suggestions={prisonerSuggestions}
          onSuggestionsChange={setPrisonerSuggestions}
        />
        <ModelSelect
          label="WARDEN"
          hint="DEFENSIVE AGENT"
          value={wardenModel}
          onChange={setWardenModel}
          models={models.filter((model) => model !== prisonerModel)}
          loading={modelsQuery.isPending}
          suggestions={wardenSuggestions}
          onSuggestionsChange={setWardenSuggestions}
        />
      </div>

      {modelsQuery.isError && (
        <p className="mt-5 text-sm text-destructive">
          FAILED TO LOAD MODELS: {(modelsQuery.error as Error).message}
        </p>
      )}

      {prisonerModel !== "" && prisonerModel === wardenModel && (
        <p className="mt-5 text-sm text-destructive">
          PRISONER AND WARDEN CANNOT USE THE SAME MODEL.
        </p>
      )}

      {launch.isError && (
        <p className="mt-5 text-sm text-destructive">
          FAILED TO START MATCH: {(launch.error as Error).message}
        </p>
      )}

      <div className="mt-7 flex flex-wrap gap-3">
        <Button
          onClick={() => launch.mutate()}
          disabled={!ready}
          className="h-12 rounded-none px-6 font-mono text-sm font-bold"
        >
          {launch.isPending ? "QUEUEING MATCH..." : "START MATCH"}
        </Button>
        <Button asChild variant="secondary" className="h-12 rounded-none">
          <Link to="/challenges">CANCEL</Link>
        </Button>
      </div>

      {launch.isPending && (
        <p className="mt-4 text-[11px] text-muted-foreground">
          Queueing on the worker... you will be moved to the live spectate view.
        </p>
      )}
    </main>
  );
}

function ModelSelect({
  label,
  hint,
  value,
  onChange,
  models,
  loading,
  suggestions,
  onSuggestionsChange,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
  models: string[];
  loading: boolean;
  suggestions: string;
  onSuggestionsChange: (value: string) => void;
}) {
  return (
    <div className="data-panel p-5">
      <span className="flex items-baseline justify-between">
        <span className="text-sm font-bold text-primary">{label}</span>
        <span className="text-[11px] text-muted-foreground">{hint}</span>
      </span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={loading}
        aria-label={`${label} model`}
        className="mt-4 w-full border border-border bg-background px-3 py-3 text-sm text-foreground"
      >
        <option value="">
          {loading ? "LOADING MODELS..." : "SELECT MODEL"}
        </option>
        {models.map((model) => (
          <option key={model} value={model}>
            {model}
          </option>
        ))}
      </select>

      {/* Shown only once a model is chosen, so the form stays compact. */}
      {value !== "" && (
        <textarea
          value={suggestions}
          onChange={(event) => onSuggestionsChange(event.target.value)}
          placeholder="Any suggestions for the agent..."
          rows={3}
          maxLength={2000}
          aria-label={`${label} suggestions`}
          className="mt-3 w-full resize-y border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
        />
      )}
    </div>
  );
}
