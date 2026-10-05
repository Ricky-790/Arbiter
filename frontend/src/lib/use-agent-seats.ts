import { useEffect, useRef, useState } from "react";

import { verifyModel } from "@/lib/api";
import type { AvailableModelsResponse } from "@/lib/dto";

/** How long typing must pause before a model name is checked with its provider. */
const CHECK_DEBOUNCE_MS = 400;

/**
 * Where a model name stands with its provider.
 *
 * `unreachable` is kept apart from `invalid` so the operator can tell "that name
 * is wrong" from "we could not ask right now"; both block the match, because an
 * unconfirmed name could still occupy a sandbox and produce nothing.
 */
export type ModelCheckStatus =
  "idle" | "checking" | "ok" | "invalid" | "unreachable";

export type ModelCheck = {
  status: ModelCheckStatus;
  detail: string | null;
};

const IDLE_CHECK: ModelCheck = { status: "idle", detail: null };

/** One side's seat: which provider and model, and what the operator typed. */
export type AgentSeat = {
  provider: string;
  model: string;
  /** Every model is BYOK, so a seated side always needs the caller's key. */
  needsKey: boolean;
  apiKey: string;
  /**
   * A saved strategy this side runs instead, or null when the operator is
   * writing their own. The two are alternatives: a side runs either a library
   * entry or the text below, never both.
   */
  strategyId: string | null;
  suggestions: string;
  /** Whether the provider confirmed this model name. */
  check: ModelCheck;
};

/** The mutable half of a seat; `needsKey`/`check` are derived, not stored. */
type SeatState = Pick<
  AgentSeat,
  "provider" | "model" | "apiKey" | "strategyId" | "suggestions"
>;

export type SeatSide = "prisoner" | "warden";

/** A provider/model pair offered as the picker's starting point. */
export type SeatDefault = {
  provider: string;
  model: string;
};

/** A pair from the parent of a fork, used to pre-fill the pickers. */
export type SeatDefaults = {
  prisoner?: SeatDefault | null | undefined;
  warden?: SeatDefault | null | undefined;
};

/**
 * Both sides' strategy choices, shaped for a start request.
 *
 * A side runs a saved strategy *or* the operator's own text, so this sends the
 * id with null suggestions, or null id with the text. Sending both would leave
 * the backend to decide which wins, which is not a decision the form should be
 * making on the operator's behalf.
 */
export function seatStrategyPayloads(seats: Record<SeatSide, AgentSeat>): {
  prisoner_strategy_id: string | null;
  prisoner_suggestions: string | null;
  warden_strategy_id: string | null;
  warden_suggestions: string | null;
} {
  const side = (seat: AgentSeat) =>
    seat.strategyId !== null
      ? { id: seat.strategyId, suggestions: null }
      : { id: null, suggestions: seat.suggestions.trim() || null };

  const prisoner = side(seats.prisoner);
  const warden = side(seats.warden);

  return {
    prisoner_strategy_id: prisoner.id,
    prisoner_suggestions: prisoner.suggestions,
    warden_strategy_id: warden.id,
    warden_suggestions: warden.suggestions,
  };
}

/** The suggested models `provider` offers, or `[]` if it is not in the catalogue. */
export function modelsForProvider(
  models: AvailableModelsResponse,
  provider: string,
): string[] {
  return (
    models.providers.find((entry) => entry.provider === provider)?.models ?? []
  );
}

/**
 * The `provider:model` identity of a seat, or `""` while it is incomplete.
 *
 * Two sides may share a provider or a model, but not the pair, so this is what
 * both the duplicate check and the request payload are built from.
 */
export function seatModelKey(seat: AgentSeat): string {
  if (seat.provider === "" || seat.model === "") return "";
  return `${seat.provider}:${seat.model}`;
}

/**
 * Ask the backend whether a provider serves this model, debounced.
 *
 * Fires once the side has a provider, a model name and a key: the key is what
 * the backend uses to read the provider's model list, so nothing can be checked
 * before it is entered. A stale request is aborted when the input changes, so a
 * slow answer for an old name cannot overwrite a newer one.
 */
function useModelCheck(
  provider: string,
  model: string,
  apiKey: string,
): ModelCheck {
  const [check, setCheck] = useState<ModelCheck>(IDLE_CHECK);

  useEffect(() => {
    if (provider === "" || model === "" || apiKey.trim() === "") {
      setCheck(IDLE_CHECK);
      return;
    }

    const controller = new AbortController();
    let cancelled = false;
    setCheck({ status: "checking", detail: null });

    const timer = setTimeout(() => {
      verifyModel(
        { provider, model, api_key: apiKey.trim() },
        controller.signal,
      )
        .then((result) => {
          if (cancelled) return;
          setCheck(
            result.exists
              ? { status: "ok", detail: null }
              : {
                  status:
                    result.reason === "unreachable" ? "unreachable" : "invalid",
                  detail: result.detail,
                },
          );
        })
        .catch((error: unknown) => {
          // An abort is our own doing, not a failure to report.
          if (cancelled) return;
          setCheck({
            status: "unreachable",
            detail:
              error instanceof Error
                ? error.message
                : "Could not verify this model.",
          });
        });
    }, CHECK_DEBOUNCE_MS);

    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [provider, model, apiKey]);

  return check;
}

/**
 * The two seat assignments shared by the launch and start-from-fork pages.
 *
 * Both flows make the same choice under the same rules — a provider and a model
 * per side, no repeating the other side's exact pair, a key for each side, a
 * model name the provider confirms, and a strategy that is either a saved library
 * entry or the operator's own text but never both — so the rules live here instead
 * of in each form.
 *
 * `defaults` pre-fills a side once the catalogue has loaded, and only if the
 * suggested pair is still offered; a side the caller has since chosen is never
 * touched.
 */
export function useAgentSeats(
  models: AvailableModelsResponse,
  defaults?: SeatDefaults,
) {
  const [prisoner, setPrisoner] = useState<SeatState>(emptySeat);
  const [warden, setWarden] = useState<SeatState>(emptySeat);

  const prefilled = useRef<Record<SeatSide, boolean>>({
    prisoner: false,
    warden: false,
  });

  useEffect(() => {
    if (defaults === undefined || models.providers.length === 0) return;
    for (const side of ["prisoner", "warden"] as const) {
      if (prefilled.current[side]) continue;
      const wanted = defaults[side];
      if (wanted === null || wanted === undefined) continue;
      if (!modelsForProvider(models, wanted.provider).includes(wanted.model)) {
        continue;
      }
      prefilled.current[side] = true;
      const setter = side === "prisoner" ? setPrisoner : setWarden;
      setter((current) =>
        current.provider === "" && current.model === ""
          ? { ...current, provider: wanted.provider, model: wanted.model }
          : current,
      );
    }
  }, [models, defaults]);

  const update = (side: SeatSide, mutate: (seat: SeatState) => SeatState) => {
    const setter = side === "prisoner" ? setPrisoner : setWarden;
    setter((current) => mutate(current));
  };

  /**
   * Switch provider, dropping the model and the key with it: the models differ
   * per provider, and a key pasted for the previous provider will not work.
   */
  const chooseProvider = (side: SeatSide, provider: string) => {
    update(side, (seat) => ({ ...seat, provider, model: "", apiKey: "" }));
  };

  const chooseModel = (side: SeatSide, model: string) => {
    update(side, (seat) => ({ ...seat, model }));
  };

  const setApiKey = (side: SeatSide, apiKey: string) => {
    update(side, (seat) => ({ ...seat, apiKey }));
  };

  /**
   * Run a saved strategy on this side, in place of anything typed.
   *
   * Choosing one clears the operator's own text: the backend treats a strategy
   * id and free-text suggestions for the same side as alternatives, and running
   * a stored wording alongside fresh tips would leave which one the agent sees
   * down to the worker. Passing `null` is how the operator switches back to
   * writing their own.
   */
  const chooseStrategy = (side: SeatSide, strategyId: string | null) => {
    update(side, (seat) => ({ ...seat, strategyId, suggestions: "" }));
  };

  /**
   * Edit the operator's own tips, which drops any chosen strategy for the same
   * reason `chooseStrategy` clears the text. Typing at all means "mine".
   */
  const setSuggestions = (side: SeatSide, suggestions: string) => {
    update(side, (seat) => ({ ...seat, suggestions, strategyId: null }));
  };

  const prisonerCheck = useModelCheck(
    prisoner.provider,
    prisoner.model,
    prisoner.apiKey,
  );
  const wardenCheck = useModelCheck(
    warden.provider,
    warden.model,
    warden.apiKey,
  );

  const seats: Record<SeatSide, AgentSeat> = {
    prisoner: seated(prisoner, prisonerCheck),
    warden: seated(warden, wardenCheck),
  };

  const prisonerKey = seatModelKey(seats.prisoner);
  const wardenKey = seatModelKey(seats.warden);

  const keyReady = (seat: AgentSeat): boolean =>
    !seat.needsKey || seat.apiKey.trim() !== "";

  const verified = (seat: AgentSeat): boolean => seat.check.status === "ok";

  /**
   * Whether both sides are assigned, distinct, and usable.
   *
   * A model the provider has not confirmed is not usable: the worker takes a
   * sandbox before its first model call, so queueing an unconfirmed name would
   * spend that sandbox on a failure.
   */
  const ready =
    prisonerKey !== "" &&
    wardenKey !== "" &&
    prisonerKey !== wardenKey &&
    keyReady(seats.prisoner) &&
    keyReady(seats.warden) &&
    verified(seats.prisoner) &&
    verified(seats.warden);

  return {
    seats,
    ready,
    chooseProvider,
    chooseModel,
    setApiKey,
    chooseStrategy,
    setSuggestions,
  };
}

/** A seat needs a key once it names a model. */
function seated(seat: SeatState, check: ModelCheck): AgentSeat {
  return {
    ...seat,
    needsKey: seat.provider !== "" && seat.model !== "",
    check,
  };
}

function emptySeat(): SeatState {
  return {
    provider: "",
    model: "",
    apiKey: "",
    strategyId: null,
    suggestions: "",
  };
}
