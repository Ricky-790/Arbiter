import { useEffect, useMemo, useRef, useState } from "react";

import type { AvailableModelsResponse } from "@/lib/dto";

/** One side's seat: which model, whether it needs a key, and what was typed. */
export type AgentSeat = {
  model: string;
  /** A BYOK model runs on the caller's own key, so the side needs one. */
  needsKey: boolean;
  apiKey: string;
  suggestions: string;
};

export type SeatSide = "prisoner" | "warden";

/** A model offered as the picker's starting point, from the parent of a fork. */
export type SeatDefaults = {
  prisoner?: string | null | undefined;
  warden?: string | null | undefined;
};

/**
 * The two seat assignments shared by the launch and start-from-fork pages.
 *
 * Both flows make the same choice under the same rules — one model per side, no
 * repeating the other side's model, and a key only while a BYOK model is picked
 * (choosing a free model drops a key typed for the previous choice) — so the
 * rules live here instead of in each form.
 *
 * `defaults` pre-fills a side once the catalogue has loaded, and only if the
 * model is still offered; a side the caller has since chosen is never touched.
 */
export function useAgentSeats(
  models: AvailableModelsResponse,
  defaults?: SeatDefaults,
) {
  const [prisoner, setPrisoner] = useState<AgentSeat>(emptySeat);
  const [warden, setWarden] = useState<AgentSeat>(emptySeat);

  const byokModels = useMemo(() => new Set(models.byok_models), [models]);
  const catalogue = useMemo(
    () => [...models.free_models, ...models.byok_models],
    [models],
  );
  const prefilled = useRef<Record<SeatSide, boolean>>({
    prisoner: false,
    warden: false,
  });

  useEffect(() => {
    if (defaults === undefined || catalogue.length === 0) return;
    for (const side of ["prisoner", "warden"] as const) {
      if (prefilled.current[side]) continue;
      const model = defaults[side];
      if (model === null || model === undefined || !catalogue.includes(model)) {
        continue;
      }
      prefilled.current[side] = true;
      if (side === "prisoner") {
        setPrisoner((current) =>
          current.model === "" ? { ...current, model } : current,
        );
      } else {
        setWarden((current) =>
          current.model === "" ? { ...current, model } : current,
        );
      }
    }
  }, [catalogue, defaults]);

  const update = (side: SeatSide, mutate: (seat: AgentSeat) => AgentSeat) => {
    const setter = side === "prisoner" ? setPrisoner : setWarden;
    setter((current) => mutate(current));
  };

  const choose = (side: SeatSide, model: string) => {
    update(side, (seat) => ({
      ...seat,
      model,
      apiKey: byokModels.has(model) ? seat.apiKey : "",
    }));
  };

  const setApiKey = (side: SeatSide, apiKey: string) => {
    update(side, (seat) => ({ ...seat, apiKey }));
  };

  const setSuggestions = (side: SeatSide, suggestions: string) => {
    update(side, (seat) => ({ ...seat, suggestions }));
  };

  const seats: Record<SeatSide, AgentSeat> = {
    prisoner: { ...prisoner, needsKey: byokModels.has(prisoner.model) },
    warden: { ...warden, needsKey: byokModels.has(warden.model) },
  };

  const keyReady = (seat: AgentSeat): boolean =>
    !seat.needsKey || seat.apiKey.trim() !== "";

  /** Whether both sides are assigned and usable. */
  const ready =
    seats.prisoner.model !== "" &&
    seats.warden.model !== "" &&
    seats.prisoner.model !== seats.warden.model &&
    keyReady(seats.prisoner) &&
    keyReady(seats.warden);

  return { seats, ready, choose, setApiKey, setSuggestions };
}

function emptySeat(): AgentSeat {
  return { model: "", needsKey: false, apiKey: "", suggestions: "" };
}
