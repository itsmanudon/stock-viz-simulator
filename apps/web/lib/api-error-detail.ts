/** The API's `detail` text from an authed call's error body, else a fallback. */
export function apiDetail(detail: string, fallback: string): string {
  try {
    const parsed = JSON.parse(detail) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail) return parsed.detail;
  } catch {
    // not JSON
  }
  return fallback;
}
