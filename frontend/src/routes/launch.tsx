import { useMutation, useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { Eyebrow } from "@/components/arbiter/app-shell";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { getChallenge, listModels, startMatch } from "@/lib/api";
import type { AvailableModelsResponse } from "@/lib/dto";

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
  const [prisonerApiKey, setPrisonerApiKey] = useState("");
  const [wardenApiKey, setWardenApiKey] = useState("");

  const modelsQuery = useQuery({
    queryKey: ["free-models"],
    queryFn: listModels,
  });

  const challengeQuery = useQuery({
    queryKey: ["challenge", challengeId],
    queryFn: () => getChallenge(challengeId),
    enabled: challengeId !== "",
  });

  const models: AvailableModelsResponse = modelsQuery.data ?? {
    free_models: [],
    byok_models: [],
  };
  const byokModels = new Set(models.byok_models);
  const prisonersNeedsKey = byokModels.has(prisonerModel);
  const wardenNeedsKey = byokModels.has(wardenModel);

  /** Selecting a free model drops any key typed for the previous choice. */
  const chooseModel = (
    next: string,
    setModel: (value: string) => void,
    setApiKey: (value: string) => void,
  ) => {
    setModel(next);
    if (!byokModels.has(next)) setApiKey("");
  };

  const launch = useMutation({
    mutationFn: () =>
      startMatch({
        challenge_id: challengeId,
        prisoner_model: prisonerModel,
        warden_model: wardenModel,
        prisoner_suggestions: prisonerSuggestions.trim() || null,
        warden_suggestions: wardenSuggestions.trim() || null,
        // Only ever sent for the side that needs it; a free model runs on the
        // deployment's own key.
        prisoner_api_key: prisonersNeedsKey ? prisonerApiKey.trim() : null,
        warden_api_key: wardenNeedsKey ? wardenApiKey.trim() : null,
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

  const challenge = challengeQuery.data ?? null;
  const ready =
    challengeId !== "" &&
    prisonerModel !== "" &&
    wardenModel !== "" &&
    prisonerModel !== wardenModel &&
    (!prisonersNeedsKey || prisonerApiKey.trim() !== "") &&
    (!wardenNeedsKey || wardenApiKey.trim() !== "") &&
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
      {/*<Eyebrow>LAUNCH_MATCH</Eyebrow>*/}
      <h1 className="mt-4 font-display text-3xl font-bold">Select Agents</h1>
      <p className="mt-3 text-sm text-muted-foreground">
        Choose one model per side.
      </p>

      <div className="data-panel mt-7 p-5">
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
            <div className="text-md font-bold">{challenge.name}</div>
            <p className="mt-2 text-md leading-5 text-muted-foreground">
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
          hint="Attacker"
          value={prisonerModel}
          onChange={(next) =>
            chooseModel(next, setPrisonerModel, setPrisonerApiKey)
          }
          models={models}
          excluded={wardenModel}
          loading={modelsQuery.isPending}
          suggestions={prisonerSuggestions}
          onSuggestionsChange={setPrisonerSuggestions}
          needsKey={prisonersNeedsKey}
          apiKey={prisonerApiKey}
          onApiKeyChange={setPrisonerApiKey}
        />
        <ModelSelect
          label="WARDEN"
          hint="Defender"
          value={wardenModel}
          onChange={(next) =>
            chooseModel(next, setWardenModel, setWardenApiKey)
          }
          models={models}
          excluded={prisonerModel}
          loading={modelsQuery.isPending}
          suggestions={wardenSuggestions}
          onSuggestionsChange={setWardenSuggestions}
          needsKey={wardenNeedsKey}
          apiKey={wardenApiKey}
          onApiKeyChange={setWardenApiKey}
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
  excluded,
  loading,
  suggestions,
  onSuggestionsChange,
  needsKey,
  apiKey,
  onApiKeyChange,
}: {
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
  models: AvailableModelsResponse;
  /** The other side's pick, which this side may not repeat. */
  excluded: string;
  loading: boolean;
  suggestions: string;
  onSuggestionsChange: (value: string) => void;
  needsKey: boolean;
  apiKey: string;
  onApiKeyChange: (value: string) => void;
}) {
  const freeModels = models.free_models.filter((model) => model !== excluded);
  const byokModels = models.byok_models.filter((model) => model !== excluded);

  return (
    <div className="data-panel p-5">
      <span className="flex items-baseline justify-between">
        <span className="text-sm font-bold text-primary">{label}</span>
        <span className="text-[11px] text-muted-foreground">{hint}</span>
      </span>

      <Select value={value} onValueChange={onChange} disabled={loading}>
        <SelectTrigger
          aria-label={`${label} model`}
          className="mt-4 h-auto w-full rounded-none border-border bg-background px-3 py-3 text-sm data-[placeholder]:text-muted-foreground"
        >
          <SelectValue
            placeholder={loading ? "LOADING MODELS..." : "SELECT MODEL"}
          />
        </SelectTrigger>
        {/* Capped so the catalogue scrolls instead of running off the screen.
            The accent scrollbar lives on the viewport (see ui/select.tsx). */}
        <SelectContent className="max-h-[min(18rem,var(--radix-select-content-available-height))] rounded-none border-border bg-panel">
          <SelectGroup>
            <SelectLabel className="font-mono text-[10px] uppercase text-muted-foreground">
              FREE MODELS
            </SelectLabel>
            <SelectSeparator className="bg-border" />
            {freeModels.map((model) => (
              <SelectItem
                key={model}
                value={model}
                className="cursor-pointer rounded-none text-sm"
              >
                {model}
              </SelectItem>
            ))}
          </SelectGroup>
          <SelectSeparator className="bg-border" />
          <SelectGroup>
            <SelectLabel className="font-mono text-[10px] uppercase text-primary">
              BYOK MODELS
            </SelectLabel>
            <SelectSeparator className="bg-border" />
            {byokModels.map((model) => (
              <SelectItem
                key={model}
                value={model}
                className="cursor-pointer rounded-none text-sm"
              >
                {model}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>

      {/* A BYOK model runs on the player's own key, so ask for it inline. */}
      {needsKey && (
        <div className="mt-3">
          <label
            htmlFor={`${label}-api-key`}
            className="text-[10px] text-muted-foreground"
          >
            {label} API KEY
          </label>
          <input
            id={`${label}-api-key`}
            type="password"
            value={apiKey}
            onChange={(event) => onApiKeyChange(event.target.value)}
            placeholder="Paste your provider API key"
            autoComplete="off"
            spellCheck={false}
            aria-label={`${label} API key`}
            className="mt-1 w-full border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground"
          />
          <p className="mt-1 text-[10px] text-muted-foreground">
            Used for this match only.
          </p>
        </div>
      )}

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
