/** The API's `detail` from an error body: a string, or the first validation message. */
export function apiDetailMessage(detail: string, fallback: string): string {
  try {
    const parsed = JSON.parse(detail) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (Array.isArray(parsed.detail)) {
      const first = parsed.detail[0] as { msg?: string } | undefined;
      if (first?.msg) return first.msg;
    }
  } catch {
    // not JSON
  }
  return detail || fallback;
}
