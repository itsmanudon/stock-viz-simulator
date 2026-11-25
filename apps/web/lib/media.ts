/** `matchMedia(query).matches`, false where matchMedia does not exist (tests, old engines). */
export function mediaMatches(query: string): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(query).matches
    : false;
}
