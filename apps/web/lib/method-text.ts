/**
 * API method notes are sometimes written as a Markdown list in a docstring
 * ("Per day: - **ATM IV:** the mean ... - **PCR (OI):** ..."). Shown as one
 * paragraph they read as raw asterisks (inside redesign audit, 27 Nov 2026).
 * `methodParts` splits such a note into its lead and labelled items, and
 * strips Markdown emphasis and code ticks. A note without a list comes back
 * as the lead alone. Pure and client-safe.
 */

/** `joined`: the label ran into the sentence ("**IV rank** over ..."), so no colon follows it. */
export type MethodItem = { label: string | null; text: string; joined?: boolean };

function clean(text: string): string {
  return text
    .replace(/``([^`]+)``/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

export function methodParts(note: string): { lead: string; items: MethodItem[] } {
  const pieces = note.split(/\s+-\s+(?=\*\*)/);
  const lead = clean(pieces[0] ?? "");
  const items = pieces.slice(1).map((piece) => {
    const match = piece.match(/^\*\*([^*]+?)\*\*(:?)\s*([\s\S]*)$/);
    if (!match) return { label: null, text: clean(piece) };
    const raw = clean(match[1]);
    const colon = raw.endsWith(":") || match[2] === ":";
    return { label: raw.replace(/:$/, ""), text: clean(match[3]), joined: !colon };
  });
  return { lead, items };
}
