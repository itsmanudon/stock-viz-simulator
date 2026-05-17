import { apiGet } from "./client";
import { authedDelete, authedPost } from "./server";

export type Comment = {
  id: number;
  user_id: number;
  user_name: string | null;
  ticker: string;
  body: string;
  parent_id: number | null;
  created_at: string;
  replies: Comment[];
};

export function listComments(ticker: string, limit = 50, offset = 0): Promise<Comment[]> {
  const qs = new URLSearchParams({ limit: String(limit), offset: String(offset) }).toString();
  return apiGet<Comment[]>(`/v1/symbols/${encodeURIComponent(ticker)}/comments?${qs}`);
}

export function postComment(
  ticker: string,
  body: { body: string; parent_id?: number | null },
): Promise<Comment> {
  return authedPost<Comment>(`/v1/symbols/${encodeURIComponent(ticker)}/comments`, body);
}

export function deleteCommentApi(id: number): Promise<void> {
  return authedDelete(`/v1/comments/${id}`);
}
