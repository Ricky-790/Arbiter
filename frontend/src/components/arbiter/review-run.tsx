import { useMutation } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import {
  ArrowUpRight,
  Check,
  Copy,
  Loader2,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Eyebrow } from "@/components/arbiter/app-shell";
import { listModels, reviewStrategy } from "@/lib/api";
import type {
  AvailableModelsResponse,
  MatchSide,
  ReviewEvent,
} from "@/lib/dto";
import { formatArguments } from "@/lib/format";
import { modelsForProvider } from "@/lib/use-agent-seats";
import { useQuery } from "@tanstack/react-query";

/** One line of the review's progress log. */
type LogLine = {
  id: number;
  tone: "started" | "call" | "result" | "error";
  text: string;
};

const NO_MODELS: AvailableModelsResponse = { providers: [] };

/** The match a proposal can be tried on again: its challenge and its two models. */
export type MatchHandoff = {
  challengeId: string;
  prisonerProvider: string;
  prisonerModel: string;
  wardenProvider: string;
  wardenModel: string;
};

/**
 * Run the strategy reviewer over the match on screen.
 *
 * The reviewer is an LLM agent with read-only tools, and it is BYOK like every
 * other model here, so this asks for a provider, a model and a key before it can
 * run. The key travels in the request body rather than the query string, which is
 * the backend's rule as well as this one's.
 *
 * What streams is what the review *does* — one line per read the agent makes —
 * never the model's private reasoning, which Arbiter does not capture. The run
 * ends with a proposed strategy, which is shown for copying and deliberately not
 * saved: promoting it is a separate, deliberate call.
 */
export function ReviewRun({
  strategyId,
  matchId,
  side,
  challengerName,
  handoff,
}: {
  strategyId: string;
  matchId: string;
  side: MatchSide;
  /** The side's model in the match under review, for the prompt's context. */
  challengerName: string;
  /**
   * What "Try a match" carries to the launch page: the challenge both models
   * ran on. The keys are not part of it — those are the operator's to paste.
   */
  handoff: MatchHandoff;
}) {
  const navigate = useNavigate();
  const modelsQuery = useQuery({ queryKey: ["models"], queryFn: listModels });
  const models = modelsQuery.data ?? NO_MODELS;

  const [provider, setProvider] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [log, setLog] = useState<LogLine[]>([]);
  const [proposal, setProposal] = useState("");
  const [copied, setCopied] = useState(false);

  const proposalRef = useRef<HTMLTextAreaElement | null>(null);
  const nextId = useRef(0);
  const append = (tone: LogLine["tone"], text: string) => {
    const id = nextId.current++;
    setLog((current) => [...current, { id, tone, text }]);
  };

  const run = useMutation({
    mutationFn: async () => {
      const controller = new AbortController();
      // A run that navigates away must not leave the request running.
      stopRef.current = () => controller.abort();
      await reviewStrategy(
        {
          strategy_id: strategyId,
          match_id: matchId,
          provider,
          model,
          api_key: apiKey.trim(),
        },
        (event: ReviewEvent) => onFrame(event, append, setProposal),
        controller.signal,
      );
    },
    onSuccess: () => {
      stopRef.current = null;
    },
    onError: (error) => {
      stopRef.current = null;
      append(
        "error",
        error instanceof Error ? error.message : "The review could not run.",
      );
    },
  });

  const stopRef = useRef<(() => void) | null>(null);

  const seated = provider !== "" && model !== "" && apiKey.trim() !== "";
  const busy = run.isPending;

  const copy = async () => {
    // The async clipboard API needs a secure context and can still be refused,
    // so fall back to selecting the text: "press Ctrl+C" always works, and the
    // proposal is the one thing on this page the user must not lose.
    try {
      await navigator.clipboard.writeText(proposal);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      const field = proposalRef.current;
      if (field === null) return;
      field.focus();
      field.select();
      setCopied(false);
      toast("Strategy selected", {
        description: "Copy it with your keyboard shortcut.",
      });
    }
  };

  /**
   * Send the proposal to the launch page.
   *
   * The challenge and both models come from the match just reviewed, so the same
   * two agents face each other again; the proposal lands in the strategy box of
   * the side it is for. Keys stay behind: they are per-provider secrets, and a
   * URL is the last place one should ever be.
   */
  const tryAMatch = () => {
    navigate({
      to: "/launch",
      search: {
        challengeId: handoff.challengeId,
        prisoner_provider: handoff.prisonerProvider,
        prisoner_model: handoff.prisonerModel,
        warden_provider: handoff.wardenProvider,
        warden_model: handoff.wardenModel,
        [side === "prisoner" ? "prisoner_strategy" : "warden_strategy"]:
          proposal,
      },
    });
  };

  return (
    <section className="review-brief">
      <div className="review-brief-head">
        <Eyebrow>AI review</Eyebrow>
        <h2>Run an analysis.</h2>
        <p>
          An agent reads this match the way you just did and proposes a better{" "}
          {side} strategy. It is BYOK like every other model here, so it needs
          your key.
          {challengerName !== "" && <> Running as {challengerName}.</>} Nothing
          is saved — the proposal is yours to take or leave.
        </p>
      </div>

      <div className="review-brief-body">
        <div className="review-run-seats">
          <Select value={provider} onValueChange={setProvider} disabled={busy}>
            <SelectTrigger
              aria-label="Reviewer provider"
              className="select-trigger"
            >
              <SelectValue
                placeholder={
                  modelsQuery.isPending ? "Loading providers..." : "Provider"
                }
              />
            </SelectTrigger>
            <SelectContent>
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

          {/*
           * Free text backed by a suggestion list, exactly like an agent's model
           * field on the launch page: a reviewer may well be a model the
           * catalogue does not carry, and a select could only ever offer the
           * curated names. The backend confirms the name against the provider
           * before it opens the stream, so a wrong one is a plain 400.
           */}
          <input
            className="field-input"
            list="reviewer-model-options"
            value={model}
            onChange={(event) => setModel(event.target.value)}
            disabled={busy || provider === ""}
            placeholder={
              provider === ""
                ? "Select a provider first"
                : "Pick or paste a model name"
            }
            autoComplete="off"
            spellCheck={false}
            aria-label="Reviewer model"
          />
          <datalist id="reviewer-model-options">
            {modelsForProvider(models, provider).map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>

          <input
            type="password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder="Reviewer API key"
            aria-label="Reviewer API key"
            className="field-input"
            autoComplete="off"
            spellCheck={false}
            disabled={busy}
          />
        </div>

        <div className="review-run-actions">
          {busy ? (
            <button
              type="button"
              className="button-secondary"
              onClick={() => stopRef.current?.()}
            >
              Stop
            </button>
          ) : (
            <button
              type="button"
              className="button-primary"
              onClick={() => {
                setLog([]);
                setProposal("");
                run.mutate();
              }}
              disabled={!seated}
            >
              <Sparkles className="size-3.5" />
              Run AI analysis
            </button>
          )}
        </div>

        {log.length > 0 && (
          <div className="review-log" aria-live="polite">
            {log.map((line) => (
              <p className={`review-log-line is-${line.tone}`} key={line.id}>
                {line.text}
              </p>
            ))}
            {busy && (
              <p className="review-log-line is-pending">
                <Loader2 className="size-3 animate-spin" aria-hidden="true" />
                Reviewing...
              </p>
            )}
          </div>
        )}

        {proposal !== "" && (
          <div className="review-proposal">
            <div className="review-proposal-head">
              <Eyebrow>Proposed strategy</Eyebrow>
              <div className="review-proposal-actions">
                <button
                  type="button"
                  className="button-quiet"
                  onClick={copy}
                  disabled={busy}
                >
                  {copied ? (
                    <Check className="size-3.5" />
                  ) : (
                    <Copy className="size-3.5" />
                  )}
                  {copied ? "Copied" : "Copy"}
                </button>
                <button
                  type="button"
                  className="button-primary"
                  onClick={tryAMatch}
                  disabled={busy || handoff.challengeId === ""}
                >
                  Try a match
                  <ArrowUpRight className="size-3.5" />
                </button>
              </div>
            </div>
            <textarea
              ref={proposalRef}
              value={proposal}
              onChange={(event) => setProposal(event.target.value)}
              rows={8}
              aria-label="Proposed strategy"
              className="field-textarea review-proposal-text"
            />
            <p className="review-proposal-note">
              <TriangleAlert className="size-3.5" />A proposal, not a saved
              strategy. Nothing was written to the library.
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

/** Turn one streamed frame into a log line, and keep the proposal if it is one. */
function onFrame(
  event: ReviewEvent,
  append: (tone: LogLine["tone"], text: string) => void,
  setProposal: (text: string) => void,
): void {
  switch (event.type) {
    case "review_started":
      append("started", "Review started — reading the match.");
      return;
    case "review_tool_call":
      append(
        "call",
        `Reading: ${event.tool ?? "tool"} ${formatArguments(event.arguments)}`,
      );
      return;
    case "review_tool_result":
      append(
        event.success === false ? "error" : "result",
        event.success === false
          ? `Failed: ${event.tool ?? "tool"} — ${event.error ?? "no reason given"}`
          : `Read ${event.tool ?? "tool"}.`,
      );
      return;
    case "review_finished":
      append("result", "Review complete — proposal below.");
      if (event.output !== undefined) setProposal(event.output);
      return;
    case "review_error":
      append("error", `Review failed: ${event.detail ?? "no reason given"}`);
      return;
    default:
      append("result", `Unrecognised frame: ${event.type}`);
  }
}
