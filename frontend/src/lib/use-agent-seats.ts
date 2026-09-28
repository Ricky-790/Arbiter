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
  suggestions: string;
  /** Whether the provider confirmed this model name. */
  check: ModelCheck;
};

/** The mutable half of a seat; `needsKey`/`check` are derived, not stored. */
type SeatState = Pick<
  AgentSeat,
  "provider" | "model" | "apiKey" | "suggestions"
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
 * per side, no repeating the other side's exact pair, a key for each side, and
 * a model name the provider confirms — so the rules live here instead of in
 * each form.
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

  const setSuggestions = (side: SeatSide, suggestions: string) => {
    update(side, (seat) => ({ ...seat, suggestions }));
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
  return { provider: "", model: "", apiKey: "", suggestions: "" };
}
