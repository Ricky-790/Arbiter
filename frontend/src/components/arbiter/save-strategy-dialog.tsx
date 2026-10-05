import { X } from "lucide-react";

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
import { oneLineDescription } from "@/lib/format";
import type { MatchSide } from "@/lib/dto";

/**
 * Confirms promoting one side's strategy into the library.
 *
 * The description is shown rather than asked for: `save-strategy` takes only the
 * match and the side, and derives the label from the strategy text so the two
 * cannot drift. It is previewed here read-only, matching what will be stored.
 *
 * The mutation and its error live in the view that opened this, so a rejected
 * request can stay open with the exact reason the backend gave.
 */
export function SaveStrategyDialog({
  open,
  side,
  strategy,
  pending,
  error,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  /** The side being promoted, for the copy. */
  side: MatchSide | null;
  /** That side's strategy text, as the match ran it. */
  strategy: string | null;
  pending: boolean;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  const label = side === "warden" ? "Warden" : "Prisoner";
  const description = strategy === null ? "" : oneLineDescription(strategy);

  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="fork-dialog">
        <button
          type="button"
          className="drawer-close absolute right-4 top-4"
          onClick={() => onOpenChange(false)}
          disabled={pending}
          aria-label="Close save strategy dialog"
        >
          <X className="size-4" />
        </button>

        <AlertDialogHeader>
          <p className="eyebrow">Strategy library</p>
          <AlertDialogTitle>Save this strategy?</AlertDialogTitle>
          <AlertDialogDescription>
            The {label}&apos;s strategy is promoted into the library as it ran
            here, ready to start a later match with. Nothing about this match
            changes, and saving again reuses the same entry.
          </AlertDialogDescription>
        </AlertDialogHeader>

        <div className="save-strategy-field">
          <span className="mono-label">One-line description</span>
          <p className="save-strategy-description">
            {description === "" ? "—" : description}
          </p>
          <span className="save-strategy-hint">
            Taken from the first line of the strategy, which is what the library
            lists it under.
          </span>
        </div>

        {error !== null && <p className="fork-dialog-error">{error}</p>}

        <AlertDialogFooter>
          <AlertDialogAction
            onClick={(event) => {
              // Keep the dialog open while the request is in flight so a
              // rejected save can show its reason here.
              event.preventDefault();
              onConfirm();
            }}
            disabled={pending || side === null}
          >
            {pending ? "Saving..." : "Yes, save it"}
          </AlertDialogAction>
          <AlertDialogCancel>No</AlertDialogCancel>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
