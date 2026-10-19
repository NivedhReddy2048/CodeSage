"use client";

import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { errorMessage } from "@/components/states";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";

/**
 * Owner/admin only (the API enforces it; this just hides the control from others).
 * Confirms first, because a re-run spends a full review's model quota and edits the
 * bot's comment on GitHub.
 */
export function RerunButton({ reviewId, pullRequest }: { reviewId: number; pullRequest: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      const { review_id } = await api.rerunReview(reviewId);
      setOpen(false);
      router.push(`/reviews/${review_id}`);
    } catch (err) {
      setError(errorMessage(err, "Could not start the review."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="outline" size="sm" />}>
        <RefreshCw aria-hidden="true" className="size-4" />
        Re-run review
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Re-run this review?</DialogTitle>
          <DialogDescription>
            CodeSage will review {pullRequest} again at its latest commit. That uses a full
            review&apos;s model quota and updates the CodeSage comment on GitHub. The re-run is
            recorded in the audit log.
          </DialogDescription>
        </DialogHeader>
        {error ? (
          <p role="alert" className="text-sm text-status-blocking">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
          <Button onClick={() => void confirm()} disabled={busy}>
            {busy ? "Starting..." : "Re-run review"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
