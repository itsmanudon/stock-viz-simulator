/**
 * Server-side half of the order review (UI audit UX-4).
 *
 * A ticket that has a review step (the stock page's contextual ticket) sends
 * `review_step`: "draft" until the review is open, "confirmed" from the
 * review's own button. A "draft" submission reaching the server means the
 * browser posted the form before the page's JavaScript took over (server
 * actions work without JS), which would skip the review, so the trade actions
 * refuse it. Tickets without a review step do not send the field and are
 * unaffected.
 */
export const REVIEW_REQUIRED_ERROR = "Review the order before placing it.";

export function skippedReview(formData: FormData): boolean {
  return formData.get("review_step") === "draft";
}
