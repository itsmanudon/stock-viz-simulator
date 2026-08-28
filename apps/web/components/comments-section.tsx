"use client";

import { useActionState, useState } from "react";

import {
  type PostCommentState,
  deleteCommentAction,
  postCommentAction,
} from "@/app/(product)/stocks/[ticker]/comments-actions";
import { Button } from "@/components/ui/button";
import type { Comment } from "@/lib/api/comments";

type Props = {
  ticker: string;
  comments: Comment[];
  currentUserId: number | null;
  embedded?: boolean;
};

function fmtWhen(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function CommentsSection({ ticker, comments, currentUserId, embedded = false }: Props) {
  const [open, setOpen] = useState(true);

  const totalCount = comments.reduce((sum, c) => sum + 1 + c.replies.length, 0);

  return (
    <section className={embedded ? "" : "mt-12"}>
      <div className={embedded ? "mb-4" : "mb-3 flex items-baseline justify-between gap-3"}>
        {embedded ? (
          <p className="text-sm text-muted-foreground">
            {totalCount} {totalCount === 1 ? "comment" : "comments"}
          </p>
        ) : (
          <>
            <h2 className="text-lg font-semibold">
              Discussion{" "}
              <span className="ml-1 text-sm font-normal text-muted-foreground">
                ({totalCount} {totalCount === 1 ? "comment" : "comments"})
              </span>
            </h2>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
            >
              {open ? "Collapse" : "Expand"}
            </Button>
          </>
        )}
      </div>

      {open || embedded ? (
        <div className="space-y-6">
          {currentUserId !== null ? (
            <CommentForm ticker={ticker} />
          ) : (
            <p className="rounded-md border bg-muted/30 p-3 text-sm text-muted-foreground">
              <a href="/login" className="text-foreground underline">
                Sign in
              </a>{" "}
              to join the discussion.
            </p>
          )}

          {comments.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No comments yet. Be the first to share your take.
            </p>
          ) : (
            <ul className="space-y-4">
              {comments.map((c) => (
                <li key={c.id}>
                  <CommentItem
                    comment={c}
                    ticker={ticker}
                    currentUserId={currentUserId}
                    canReply={currentUserId !== null}
                  />
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </section>
  );
}

function CommentItem({
  comment,
  ticker,
  currentUserId,
  canReply,
  isReply = false,
}: {
  comment: Comment;
  ticker: string;
  currentUserId: number | null;
  canReply: boolean;
  isReply?: boolean;
}) {
  const [replying, setReplying] = useState(false);
  const own = currentUserId !== null && currentUserId === comment.user_id;

  return (
    <div className={`rounded-md border bg-card p-3 ${isReply ? "border-dashed bg-muted/20" : ""}`}>
      <div className="mb-1 flex items-baseline gap-2 text-xs">
        <span className="font-semibold text-foreground">{comment.user_name ?? "Anonymous"}</span>
        <span className="text-muted-foreground">{fmtWhen(comment.created_at)}</span>
        {own ? (
          <form action={deleteCommentAction} className="ml-auto">
            <input type="hidden" name="id" value={comment.id} />
            <input type="hidden" name="ticker" value={ticker} />
            <button type="submit" className="text-xs text-muted-foreground hover:text-negative">
              Delete
            </button>
          </form>
        ) : null}
      </div>
      <p className="whitespace-pre-wrap text-sm">{comment.body}</p>

      {!isReply && canReply ? (
        <div className="mt-2">
          {replying ? (
            <CommentForm
              ticker={ticker}
              parentId={comment.id}
              onCancel={() => setReplying(false)}
              compact
            />
          ) : (
            <button
              type="button"
              className="text-xs text-muted-foreground hover:text-foreground"
              onClick={() => setReplying(true)}
            >
              Reply
            </button>
          )}
        </div>
      ) : null}

      {comment.replies.length > 0 ? (
        <ul className="mt-3 space-y-2 border-l-2 border-muted pl-3">
          {comment.replies.map((r) => (
            <li key={r.id}>
              <CommentItem
                comment={r}
                ticker={ticker}
                currentUserId={currentUserId}
                canReply={false}
                isReply
              />
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function CommentForm({
  ticker,
  parentId,
  onCancel,
  compact = false,
}: {
  ticker: string;
  parentId?: number;
  onCancel?: () => void;
  compact?: boolean;
}) {
  const [state, action, pending] = useActionState<PostCommentState, FormData>(
    postCommentAction,
    {},
  );

  return (
    <form action={action} className="space-y-2">
      <input type="hidden" name="ticker" value={ticker} />
      {parentId !== undefined ? <input type="hidden" name="parent_id" value={parentId} /> : null}
      <textarea
        name="body"
        rows={compact ? 2 : 3}
        required
        maxLength={2000}
        placeholder={parentId ? "Write a reply…" : "Share your take on this stock…"}
        className="w-full rounded-md border bg-background px-3 py-2 text-sm"
      />
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={pending}>
          {pending ? "Posting…" : parentId ? "Reply" : "Post comment"}
        </Button>
        {onCancel ? (
          <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        ) : null}
        {state.error ? (
          <p className="text-xs text-negative" role="alert">
            {state.error}
          </p>
        ) : state.postedAt ? (
          <p className="text-xs text-positive">Posted.</p>
        ) : null}
      </div>
    </form>
  );
}
