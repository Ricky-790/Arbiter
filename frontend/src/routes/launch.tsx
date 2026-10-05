import { useMutation, useQuery } from "@tanstack/react-query";
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, ArrowUpRight } from "lucide-react";
import { toast } from "sonner";

import { AgentSeatPicker } from "@/components/arbiter/agent-seat-picker";
import { Eyebrow } from "@/components/arbiter/app-shell";
import {
  getChallenge,
  listModels,
  listStrategies,
  startMatch,
} from "@/lib/api";
import type { AvailableModelsResponse, StrategySchema } from "@/lib/dto";
import {
  seatModelKey,
  seatStrategyPayloads,
  useAgentSeats,
} from "@/lib/use-agent-seats";

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
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: LaunchPage,
});

function LaunchPage() {
  const navigate = useNavigate();
  const { challengeId = "" } = Route.useSearch();

  const modelsQuery = useQuery({
    queryKey: ["models"],
    queryFn: listModels,
  });

  const challengeQuery = useQuery({
    queryKey: ["challenge", challengeId],
    queryFn: () => getChallenge(challengeId),
    enabled: challengeId !== "",
  });

  // A strategy only means anything against the challenge it was played on, so
  // this asks for that challenge's entries rather than the whole library.
  const strategiesQuery = useQuery({
    queryKey: ["strategies", "challenge", challengeId],
    queryFn: () => listStrategies({ challengeId, limit: 50 }),
    enabled: challengeId !== "",
  });

  const models: AvailableModelsResponse = modelsQuery.data ?? {
    providers: [],
  };
  // Each seat is only offered its own side's entries; the other side's wording
  // is not something an agent should be handed.
  const sideStrategies = splitBySide(strategiesQuery.data?.items ?? []);
  const savedCount =
    sideStrategies.prisoner.length + sideStrategies.warden.length;

  const {
    seats,
    ready,
    chooseProvider,
    chooseModel,
    setApiKey,
    chooseStrategy,
    setSuggestions,
  } = useAgentSeats(models);

  const launch = useMutation({
    mutationFn: () =>
      startMatch({
        challenge_id: challengeId,
        prisoner_provider: seats.prisoner.provider,
        prisoner_model: seats.prisoner.model,
        warden_provider: seats.warden.provider,
        warden_model: seats.warden.model,
        ...seatStrategyPayloads(seats),
        prisoner_api_key: seats.prisoner.needsKey
          ? seats.prisoner.apiKey.trim()
          : null,
        warden_api_key: seats.warden.needsKey
          ? seats.warden.apiKey.trim()
          : null,
      }),
    onSuccess: (response) => {
      toast.success("Match queued", {
        description: "Waiting for a worker to pick it up.",
      });
      navigate({
        to: "/matches",
        search: { match_id: response.match_id },
      });
    },
    onError: (error) => {
      toast.error("Could not start the match", {
        description: error instanceof Error ? error.message : "Request failed",
      });
    },
  });

  const challenge = challengeQuery.data ?? null;
  const launchReady = ready && !launch.isPending;

  if (challengeId === "") {
    return (
      <main className="page-wrap page-pad">
        <div className="page-intro">
          <div>
            <Eyebrow>Launch sequence / waiting room</Eyebrow>
            <h1 className="page-title">No arena selected.</h1>
            <p className="page-deck">
              Open a challenge brief first. Once you choose the room, this is
              where the two models take their seats.
            </p>
            <Link to="/challenges" className="button-primary mt-7">
              <ArrowLeft className="size-3.5" />
              Return to challenges
            </Link>
          </div>
          <div className="page-meta">
            <span>Sequence status</span>
            <strong>00</strong>
            <span>Awaiting scenario</span>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="page-wrap page-pad">
      <div className="page-intro">
        <div>
          <Eyebrow>Launch sequence / seat assignment</Eyebrow>
          <h1 className="page-title">Choose the two minds.</h1>
          <p className="page-deck">
            Assign one model to the Prisoner seat and one to the Warden seat.
            They must be different models; the room will supply the rest.
          </p>
        </div>
        <div className="page-meta">
          <span>Match protocol</span>
          <strong>02</strong>
          <span>Seats / tools / clock</span>
        </div>
      </div>

      <div className="launch-layout mt-8">
        <aside className="launch-aside">
          <Eyebrow>Arena brief</Eyebrow>
          <h2 className="launch-aside-title">
            {challenge?.name ?? "Loading arena"}
          </h2>
          <p className="launch-aside-copy">
            {challenge?.description ??
              "Fetching the selected challenge and its deterministic environment."}
          </p>
          <div className="launch-aside-rule" />
          <div className="launch-aside-meta">
            <div>
              <span>Exit condition</span>
              <strong>{challenge?.win_condition ?? "—"}</strong>
            </div>
            <div>
              <span>Model catalogue</span>
              <strong>{modelsQuery.isPending ? "Loading" : "Ready"}</strong>
            </div>
          </div>
        </aside>

        <section className="launch-main">
          <div className="challenge-dossier">
            <span className="mono-label">Selected scenario / dossier</span>
            {challengeQuery.isPending && (
              <p className="loading-line">Loading arena details...</p>
            )}
            {challengeQuery.isError && (
              <p className="error-line">
                Failed to load challenge:{" "}
                {(challengeQuery.error as Error).message}
              </p>
            )}
            {challenge !== null && (
              <>
                <h2 className="challenge-dossier-title">{challenge.name}</h2>
                <p className="challenge-dossier-copy">
                  {challenge.description}
                </p>
                <p className="challenge-dossier-win">
                  Win condition / {challenge.win_condition}
                </p>
              </>
            )}
          </div>

          <div className="agent-heading">
            <h2>Seat the agents</h2>
            <span className="mono-label">
              Different model required · {savedHere(savedCount)}{" "}
              {savedCount === 1 ? "strategy" : "strategies"} saved here
            </span>
          </div>
          <div className="agent-grid">
            <AgentSeatPicker
              side="prisoner"
              label="PRISONER"
              hint="Attacker"
              seat={seats.prisoner}
              models={models}
              strategies={sideStrategies.prisoner}
              excluded={seatModelKey(seats.warden)}
              loading={modelsQuery.isPending}
              onChooseProvider={(provider) =>
                chooseProvider("prisoner", provider)
              }
              onChooseModel={(model) => chooseModel("prisoner", model)}
              onApiKeyChange={(value) => setApiKey("prisoner", value)}
              onChooseStrategy={(id) => chooseStrategy("prisoner", id)}
              onSuggestionsChange={(value) => setSuggestions("prisoner", value)}
            />
            <AgentSeatPicker
              side="warden"
              label="WARDEN"
              hint="Defender"
              seat={seats.warden}
              models={models}
              strategies={sideStrategies.warden}
              excluded={seatModelKey(seats.prisoner)}
              loading={modelsQuery.isPending}
              onChooseProvider={(provider) =>
                chooseProvider("warden", provider)
              }
              onChooseModel={(model) => chooseModel("warden", model)}
              onApiKeyChange={(value) => setApiKey("warden", value)}
              onChooseStrategy={(id) => chooseStrategy("warden", id)}
              onSuggestionsChange={(value) => setSuggestions("warden", value)}
            />
          </div>

          {strategiesQuery.isError && (
            <p className="launch-status error">
              Failed to load strategies:{" "}
              {(strategiesQuery.error as Error).message} — you can still write
              your own.
            </p>
          )}

          {modelsQuery.isError && (
            <p className="launch-status error">
              Failed to load models: {(modelsQuery.error as Error).message}
            </p>
          )}

          {seatModelKey(seats.prisoner) !== "" &&
            seatModelKey(seats.prisoner) === seatModelKey(seats.warden) && (
              <p className="launch-status error">
                Prisoner and Warden cannot use the same provider and model.
              </p>
            )}

          {launch.isError && (
            <p className="launch-status error">
              Failed to start match: {(launch.error as Error).message}
            </p>
          )}

          <div className="launch-actions">
            <button
              type="button"
              onClick={() => launch.mutate()}
              disabled={!launchReady}
              className="button-primary disabled:cursor-not-allowed disabled:opacity-40"
            >
              {launch.isPending ? "Queueing match..." : "Start match"}
              <ArrowUpRight className="size-3.5" />
            </button>
            <Link to="/challenges" className="button-secondary">
              Cancel
            </Link>
          </div>

          {launch.isPending && (
            <p className="launch-status">
              Queueing on the worker... you will be moved to the live spectate
              view.
            </p>
          )}
        </section>
      </div>
    </main>
  );
}

/**
 * Split a page of strategies by the side each one is for.
 *
 * The library stores the side on the entry, and an agent should only ever be
 * handed its own side's wording, so the two lists are kept apart rather than
 * filtered again at each picker.
 */
function splitBySide(strategies: StrategySchema[]): {
  prisoner: StrategySchema[];
  warden: StrategySchema[];
} {
  return {
    prisoner: strategies.filter((entry) => entry.user === "prisoner"),
    warden: strategies.filter((entry) => entry.user === "warden"),
  };
}

/** How many strategies this challenge has saved, while that is still loading. */
function savedHere(count: number): string {
  return count === 0 ? "No" : String(count);
}
