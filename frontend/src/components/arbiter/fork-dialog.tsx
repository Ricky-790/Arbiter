import { GitBranch, X } from "lucide-react";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { formatEventTime, type EventGroup } from "@/lib/match-events";

/**
 * Confirms a fork and owns nothing but the copy: the mutation and its error live
 * in the view that opened it, so a failed request can stay in this dialog with
 * the exact reason the backend gave.
 *
 * Creating a fork does not start a match — it saves a checkpoint whose snapshot
 * and conversations the backend rebuilds in the background — so the confirmation
 * says exactly that.
 */
export function ForkDialog({
  open,
  parentMatchId,
  group,
  pending,
  error,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  parentMatchId: string;
  /** The group being branched from; null while nothing is selected. */
  group: EventGroup | null;
  pending: boolean;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  const isTurn =
    group !== null && (group.batchId !== null || group.events.length > 1);
  const callCount = group?.events.length ?? 0;

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="fork-dialog">
        <button
          type="button"
          className="drawer-close absolute right-4 top-4"
          onClick={() => onOpenChange(false)}
          disabled={pending}
          aria-label="Close fork dialog"
        >
          <X className="size-4" />
        </button>

        <AlertDialogHeader>
          <p className="eyebrow">Save a fork point</p>
          <AlertDialogTitle>
            {isTurn
              ? `Fork after the ${formatEventTime(group?.endTime ?? "")} turn.`
              : `Fork from ${formatEventTime(group?.endTime ?? "")}.`}
          </AlertDialogTitle>
          <AlertDialogDescription>
            This saves a checkpoint: the match&apos;s sandbox and each
            agent&apos;s conversation as they were at this point. It starts
            nothing — later you can run the same position as a new match with
            any models you like.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <dl className="fork-dialog-facts">
          <div>
            <dt>Parent match</dt>
            <dd>{parentMatchId}</dd>
          </div>
          <div>
            <dt>Branch event</dt>
            <dd>{group?.forkEventId ?? "—"}</dd>
          </div>
          <div>
            <dt>Steps captured</dt>
            <dd>
              {callCount} {callCount === 1 ? "step" : "steps"}
              {isTurn ? " in this turn" : ""}
            </dd>
          </div>
        </dl>

        <p className="fork-dialog-note">
          {/*<GitBranch className="size-3.5" />*/}
          {/*<span>
            Forking a match whose agent ran on a bring-your-own-key model is not
            possible, because the fork has no key to spend.
          </span>*/}
        </p>

        {error !== null && <p className="fork-dialog-error">{error}</p>}

        <AlertDialogFooter>
          <AlertDialogAction
            onClick={(event) => {
              // Keep the dialog open while the request is in flight so a
              // rejected fork can show its reason here.
              event.preventDefault();
              onConfirm();
            }}
            disabled={pending || group === null}
          >
            {pending ? "Queueing fork..." : "Save fork point"}
          </AlertDialogAction>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
