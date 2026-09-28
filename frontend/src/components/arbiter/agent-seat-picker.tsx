import { Check, KeyRound, Loader2, X } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AvailableModelsResponse } from "@/lib/dto";
import {
  type AgentSeat,
  type ModelCheck,
  type SeatSide,
  modelsForProvider,
} from "@/lib/use-agent-seats";

/**
 * One side's seat: the provider, the model under it, a key (every model is
 * BYOK), and optional tips for the agent. Shared by the launch page and the fork
 * workbench so the two make the same choice the same way.
 *
 * The model is a free-text field backed by a suggestion list, so an operator can
 * paste a name that is not curated. Whatever they enter is confirmed with the
 * provider before the match can start.
 */
export function AgentSeatPicker({
  side,
  label,
  hint,
  seat,
  models,
  excluded,
  loading,
  onChooseProvider,
  onChooseModel,
  onApiKeyChange,
  onSuggestionsChange,
}: {
  side: SeatSide;
  label: string;
  hint: string;
  seat: AgentSeat;
  models: AvailableModelsResponse;
  /** The other side's pick, as `provider:model`; this side may not repeat it. */
  excluded: string;
  loading: boolean;
  onChooseProvider: (provider: string) => void;
  onChooseModel: (model: string) => void;
  onApiKeyChange: (value: string) => void;
  onSuggestionsChange: (value: string) => void;
}) {
  const suggested = modelsForProvider(models, seat.provider).filter(
    (model) => `${seat.provider}:${model}` !== excluded,
  );

  return (
    <div className={`agent-panel ${side}`}>
      <div className="agent-panel-top">
        <span>{label}</span>
        <span className="agent-hint">{hint}</span>
      </div>

      <div className="agent-selects">
        <Select
          value={seat.provider}
          onValueChange={onChooseProvider}
          disabled={loading}
        >
          <SelectTrigger
            aria-label={`${label} provider`}
            className="select-trigger"
          >
            <SelectValue
              placeholder={loading ? "Loading providers..." : "Select provider"}
            />
          </SelectTrigger>
          <SelectContent className="max-h-[min(18rem,var(--radix-select-content-available-height))]">
            {models.providers.map((entry) => (
              <SelectItem
                key={entry.provider}
                value={entry.provider}
                className="cursor-pointer font-mono text-xs"
              >
                {entry.provider}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <div className="agent-model-row">
          <input
            id={`${side}-model`}
            className="field-input"
            // Suggestions, not a whitelist: any name can be typed or pasted.
            list={`${side}-model-options`}
            value={seat.model}
            onChange={(event) => onChooseModel(event.target.value)}
            disabled={loading || seat.provider === ""}
            placeholder={
              seat.provider === ""
                ? "Select a provider first"
                : "Pick or paste a model name"
            }
            autoComplete="off"
            spellCheck={false}
            aria-label={`${label} model`}
            aria-invalid={seat.check.status === "invalid"}
          />
          <datalist id={`${side}-model-options`}>
            {suggested.map((model) => (
              <option key={model} value={model} />
            ))}
          </datalist>
          <ModelCheckBadge check={seat.check} />
        </div>
      </div>

      {seat.check.detail !== null && seat.check.status !== "ok" && (
        <p className="model-check-detail">{seat.check.detail}</p>
      )}

      {seat.needsKey && (
        <div className="agent-key">
          <label htmlFor={`${side}-api-key`}>
            <KeyRound className="mr-1 inline size-3" />
            {seat.provider} API key
          </label>
          <input
            id={`${side}-api-key`}
            type="password"
            value={seat.apiKey}
            onChange={(event) => onApiKeyChange(event.target.value)}
            placeholder="Paste your provider API key"
            autoComplete="off"
            spellCheck={false}
            aria-label={`${label} API key`}
            className="field-input"
          />
          <p>
            Used for this match only. Enter it and the model name is checked
            with {seat.provider}.
          </p>
        </div>
      )}

      {seat.model !== "" && (
        <textarea
          value={seat.suggestions}
          onChange={(event) => onSuggestionsChange(event.target.value)}
          placeholder="Any suggestions for the agent..."
          rows={3}
          maxLength={2000}
          aria-label={`${label} suggestions`}
          className="field-textarea"
        />
      )}
    </div>
  );
}

/** The tick beside the model field: confirmed, rejected, checking, or nothing. */
function ModelCheckBadge({ check }: { check: ModelCheck }) {
  if (check.status === "idle") return null;

  if (check.status === "checking") {
    return (
      <span className="model-check is-checking" title="Checking this model...">
        <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
        <span className="sr-only">Checking this model</span>
      </span>
    );
  }

  if (check.status === "ok") {
    return (
      <span
        className="model-check is-ok"
        title="This model was confirmed with the provider"
      >
        <Check className="size-3.5" aria-hidden="true" />
        <span className="sr-only">Model confirmed</span>
      </span>
    );
  }

  return (
    <span
      className={`model-check ${check.status === "invalid" ? "is-invalid" : "is-unreachable"}`}
      title={check.detail ?? "This model could not be confirmed"}
    >
      <X className="size-3.5" aria-hidden="true" />
      <span className="sr-only">
        {check.status === "invalid"
          ? "Model not found"
          : "Could not check this model"}
      </span>
    </span>
  );
}
