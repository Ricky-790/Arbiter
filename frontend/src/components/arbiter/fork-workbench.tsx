import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { ArrowLeft, ArrowUpRight, GitBranch, X } from "lucide-react";
import { useMemo } from "react";
import { toast } from "sonner";

import { AgentSeatPicker } from "@/components/arbiter/agent-seat-picker";
import { Eyebrow } from "@/components/arbiter/app-shell";
import { ForkMemory } from "@/components/arbiter/fork-memory";
import { getChallenge, getFork, listModels, startFromFork } from "@/lib/api";
import type { AvailableModelsResponse } from "@/lib/dto";
import { formatDateTime, formatModel } from "@/lib/format";
import { isForkPending, isForkReady } from "@/lib/match-status";
import {
  seatModelKey,
  seatStrategyPayloads,
  useAgentSeats,
} from "@/lib/use-agent-seats";

const NO_MODELS: AvailableModelsResponse = { providers: [] };

/**
 * The fork workbench: what the fork remembers, and a form to run it again.
 *
 * A fork supplies the challenge, the sandbox state and each agent's
 * conversation; the caller supplies the models, the tips and the keys, so the
 * same position can be run as any number of experiments. Starting one queues an
 * ordinary match, which is why the result lands back on the canonical match URL.
 */
export function ForkWorkbench({ forkId }: { forkId: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const forkQuery = useQuery({
    queryKey: ["fork", forkId],
    queryFn: () => getFork(forkId),
    // The snapshot rebuild has no progress signal, so keep asking while it runs.
    refetchInterval: (query) =>
      isForkPending(query.state.data?.status ?? "") ? 2500 : false,
  });

  const fork = forkQuery.data ?? null;

  const challengeQuery = useQuery({
    queryKey: ["challenge", fork?.challenge_id ?? ""],
    queryFn: () => getChallenge(fork?.challenge_id ?? ""),
    enabled: fork !== null,
  });

  const modelsQuery = useQuery({
    queryKey: ["models"],
    queryFn: listModels,
  });

  const models = modelsQuery.data ?? NO_MODELS;
  // The parent match's choices are the fork's suggestion, not a requirement:
  // they pre-fill the pickers once the catalogue loads and stay editable.
  const defaults = useMemo(
    () => ({
      prisoner:
        fork?.prisoner_provider && fork?.prisoner_model
          ? { provider: fork.prisoner_provider, model: fork.prisoner_model }
          : null,
      warden:
        fork?.warden_provider && fork?.warden_model
          ? { provider: fork.warden_provider, model: fork.warden_model }
          : null,
    }),
    [
      fork?.prisoner_provider,
      fork?.prisoner_model,
      fork?.warden_provider,
      fork?.warden_model,
    ],
  );
  const {
    seats,
    ready,
    chooseProvider,
    chooseModel,
    setApiKey,
    setSuggestions,
  } = useAgentSeats(models, defaults);

  const start = useMutation({
    mutationFn: () =>
      startFromFork({
        fork_id: forkId,
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
    onSuccess: async (response) => {
      await queryClient.invalidateQueries({ queryKey: ["matches"] });
      toast.success("Match queued from fork", {
        description: "The agents resume from this point with your choices.",
      });
      navigate({
        to: "/matches",
        search: { match_id: response.match_id },
      });
    },
    onError: (error) => {
      toast.error("Could not start a match from this fork", {
        description: error instanceof Error ? error.message : "Request failed",
      });
    },
  });

  if (forkQuery.isPending) {
    return (
      <main className="page-wrap page-pad">
        <div className="match-masthead">
          <p className="eyebrow">Fork point / {forkId.slice(0, 8)}</p>
          <h1 className="page-title">Loading the fork.</h1>
          <p className="loading-line">Fetching the saved state...</p>
        </div>
      </main>
    );
  }

  if (forkQuery.isError || fork === null) {
    return (
      <main className="page-wrap page-pad">
        <div className="match-masthead">
          <p className="eyebrow">Fork point / {forkId.slice(0, 8)}</p>
          <h1 className="page-title">Fork unavailable.</h1>
          <p className="error-line">
            {forkQuery.error instanceof Error
              ? forkQuery.error.message
              : "This fork could not be found."}
          </p>
          <Link to="/archive" className="button-secondary mt-6">
            <ArrowLeft className="size-3.5" />
            Back to the archive
          </Link>
        </div>
      </main>
    );
  }

  const readyToStart = isForkReady(fork.status);
  const challenge = challengeQuery.data ?? null;

  return (
    <main className="page-wrap page-pad">
      <div className="page-intro">
        <div>
          <Eyebrow>Fork point / {fork.id.slice(0, 8)}</Eyebrow>
          <h1 className="page-title">{forkHeadline(fork.status)}</h1>
          <p className="page-deck">{forkDeck(fork.status)}</p>
        </div>
        <div className="page-meta">
          <span>Fork status</span>
          <strong className={`fork-status is-${fork.status}`}>
            <span className="fork-status-dot" aria-hidden="true" />
            {forkLabel(fork.status)}
          </strong>
          <span>Captured {formatDateTime(fork.branch_event_timestamp)}</span>
        </div>
      </div>

      <div className="launch-layout mt-8">
        <aside className="launch-aside">
          <Eyebrow>Fork dossier</Eyebrow>
          <h2 className="launch-aside-title">
            {challenge?.name ?? "Saved position"}
          </h2>
          <p className="launch-aside-copy">
            {challenge?.description ?? "The challenge this fork was taken on."}
          </p>
          <div className="launch-aside-rule" />
          <div className="launch-aside-meta">
            <div>
              <span>Parent match</span>
              <strong>
                <Link
                  to="/matches"
                  search={{ match_id: fork.parent_match_id }}
                  className="inline-link"
                >
                  {fork.parent_match_id.slice(0, 8)}
                </Link>
              </strong>
            </div>
            <div>
              <span>Branch event</span>
              <strong>{fork.branch_event_id.slice(0, 8)}</strong>
            </div>
            <div>
              <span>Captured at</span>
              <strong>{formatDateTime(fork.branch_event_timestamp)}</strong>
            </div>
            <div>
              <span>Saved</span>
              <strong>{formatDateTime(fork.created_at)}</strong>
            </div>
            {challenge !== null && (
              <div>
                <span>Exit condition</span>
                <strong>{challenge.win_condition}</strong>
              </div>
            )}
          </div>
          <div className="launch-aside-rule" />
          <p className="fork-parent-models">
            <span className="mono-label">Parent&apos;s models</span>
            <span>
              {forkModelLabel(fork.prisoner_provider, fork.prisoner_model)}{" "}
              <span className="text-muted">vs</span>{" "}
              {forkModelLabel(fork.warden_provider, fork.warden_model)}
            </span>
          </p>
        </aside>

        <section className="launch-main">
          {isForkPending(fork.status) ? (
            <div className="fork-blocked">
              <GitBranch className="size-4" />
              <div>
                <h2>Rebuilding the sandbox for this fork.</h2>
                <p>
                  The snapshot and both conversations are being restored in the
                  background. This page rechecks every couple of seconds and the
                  seat pickers unlock when the fork is ready.
                </p>
              </div>
            </div>
          ) : !readyToStart ? (
            <div className="fork-blocked is-failed">
              <X className="size-4" />
              <div>
                <h2>This fork could not be rebuilt.</h2>
                <p>
                  The snapshot the fork needs is missing, so no match can be
                  started from it. Save the point again from the parent match.
                </p>
              </div>
            </div>
          ) : (
            <>
              <ForkMemory
                turns={fork.latest_turns}
                prisonerMessages={fork.prisoner_messages}
                wardenMessages={fork.warden_messages}
              />

              <div className="agent-heading">
                <h2>Seat the agents</h2>
                <span className="mono-label">Same fork, your models</span>
              </div>
              <div className="agent-grid">
                <AgentSeatPicker
                  side="prisoner"
                  label="PRISONER"
                  hint="Attacker"
                  seat={seats.prisoner}
                  models={models}
                  excluded={seatModelKey(seats.warden)}
                  loading={modelsQuery.isPending}
                  onChooseProvider={(provider) =>
                    chooseProvider("prisoner", provider)
                  }
                  onChooseModel={(model) => chooseModel("prisoner", model)}
                  onApiKeyChange={(value) => setApiKey("prisoner", value)}
                  onSuggestionsChange={(value) =>
                    setSuggestions("prisoner", value)
                  }
                />
                <AgentSeatPicker
                  side="warden"
                  label="WARDEN"
                  hint="Defender"
                  seat={seats.warden}
                  models={models}
                  excluded={seatModelKey(seats.prisoner)}
                  loading={modelsQuery.isPending}
                  onChooseProvider={(provider) =>
                    chooseProvider("warden", provider)
                  }
                  onChooseModel={(model) => chooseModel("warden", model)}
                  onApiKeyChange={(value) => setApiKey("warden", value)}
                  onSuggestionsChange={(value) =>
                    setSuggestions("warden", value)
                  }
                />
              </div>

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

              <div className="launch-actions">
                <button
                  type="button"
                  onClick={() => start.mutate()}
                  disabled={!ready || start.isPending}
                  className="button-primary disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <GitBranch className="size-3.5" />
                  {start.isPending
                    ? "Queueing match..."
                    : "Start match from fork"}
                  <ArrowUpRight className="size-3.5" />
                </button>
                <Link to="/archive" className="button-secondary">
                  Back to the archive
                </Link>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}

/** The parent's choice as the app displays models, or a dash when unavailable. */
function forkModelLabel(provider: string | null, model: string | null): string {
  if (provider === null || model === null) return "—";
  return formatModel(provider, model);
}

function forkLabel(status: string): string {
  if (status === "ready") return "Ready";
  if (status === "pending") return "Rebuilding";
  if (status === "failed") return "Failed";
  return status;
}

/** The headline follows the fork's state: only a ready fork can be run. */
function forkHeadline(status: string): string {
  if (isForkReady(status)) return "Run this position again.";
  if (isForkPending(status)) return "Restoring this position.";
  return "This position is unavailable.";
}

function forkDeck(status: string): string {
  if (isForkReady(status)) {
    return "The sandbox and both conversations below are exactly as the parent match left them. Pick the models and start a new match from here.";
  }
  if (isForkPending(status)) {
    return "The snapshot and conversations this fork resumes from are still being rebuilt. The page rechecks on its own and the form appears once it is ready.";
  }
  return "The rebuild failed, so there is no sandbox state to resume from. Save the point again from the parent match and it will be retried.";
}
