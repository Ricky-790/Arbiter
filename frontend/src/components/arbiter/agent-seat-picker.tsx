import { KeyRound } from "lucide-react";

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
import type { AvailableModelsResponse } from "@/lib/dto";
import type { AgentSeat, SeatSide } from "@/lib/use-agent-seats";

/**
 * One side's model picker: the model, a key when the model is BYOK, and optional
 * tips for the agent. Shared by the launch page and the fork workbench so the
 * two make the same choice the same way.
 */
export function AgentSeatPicker({
  side,
  label,
  hint,
  seat,
  models,
  excluded,
  loading,
  onChoose,
  onApiKeyChange,
  onSuggestionsChange,
}: {
  side: SeatSide;
  label: string;
  hint: string;
  seat: AgentSeat;
  models: AvailableModelsResponse;
  /** The other side's pick, which this side may not repeat. */
  excluded: string;
  loading: boolean;
  onChoose: (model: string) => void;
  onApiKeyChange: (value: string) => void;
  onSuggestionsChange: (value: string) => void;
}) {
  const freeModels = models.free_models.filter((model) => model !== excluded);
  const byokModels = models.byok_models.filter((model) => model !== excluded);

  return (
    <div className={`agent-panel ${side}`}>
      <div className="agent-panel-top">
        <span>{label}</span>
        <span className="agent-hint">{hint}</span>
      </div>

      <Select value={seat.model} onValueChange={onChoose} disabled={loading}>
        <SelectTrigger aria-label={`${label} model`} className="select-trigger">
          <SelectValue
            placeholder={loading ? "Loading models..." : "Select model"}
          />
        </SelectTrigger>
        <SelectContent className="max-h-[min(18rem,var(--radix-select-content-available-height))]">
          <SelectGroup>
            <SelectLabel className="font-mono text-[10px] uppercase text-muted-foreground">
              Free models
            </SelectLabel>
            <SelectSeparator className="bg-border" />
            {freeModels.map((model) => (
              <SelectItem
                key={model}
                value={model}
                className="cursor-pointer font-mono text-xs"
              >
                {model}
              </SelectItem>
            ))}
          </SelectGroup>
          <SelectSeparator className="bg-border" />
          <SelectGroup>
            <SelectLabel className="font-mono text-[10px] uppercase text-primary">
              BYOK models
            </SelectLabel>
            <SelectSeparator className="bg-border" />
            {byokModels.map((model) => (
              <SelectItem
                key={model}
                value={model}
                className="cursor-pointer font-mono text-xs"
              >
                {model}
              </SelectItem>
            ))}
          </SelectGroup>
        </SelectContent>
      </Select>

      {seat.needsKey && (
        <div className="agent-key">
          <label htmlFor={`${side}-api-key`}>
            <KeyRound className="mr-1 inline size-3" />
            {label} API key
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
          <p>Used for this match only.</p>
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
