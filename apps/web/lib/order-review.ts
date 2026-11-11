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

/**
 * Client order keys (#67, audit LG-10). The review creates one each time it
 * opens and posts it with the confirmation, so a double click, a resubmitted
 * form or a retried request places the order once: the API returns the first
 * fill or order for a key it has seen.
 */
const CLIENT_ORDER_ID = /^[A-Za-z0-9_-]{1,64}$/;

export function newClientOrderId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  // randomUUID needs a secure context; plain-http hosts fall back to this.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** The posted key when it has the shape the API accepts, else undefined. */
export function clientOrderIdFrom(formData: FormData): string | undefined {
  const value = formData.get("client_order_id");
  return typeof value === "string" && CLIENT_ORDER_ID.test(value) ? value : undefined;
}
