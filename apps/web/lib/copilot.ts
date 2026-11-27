/** A8.5 (M11.2): pure helpers for the copilot's answer (client-safe). */

export type AnswerPart =
  | { kind: "text"; text: string }
  | { kind: "cite"; n: number; valid: boolean };

/** Split an answer into text and citation markers ("[1]", "[2, 3]"). */
export function answerParts(answer: string, sourceCount: number): AnswerPart[] {
  const parts: AnswerPart[] = [];
  const re = /\[(\d{1,2}(?:\s*,\s*\d{1,2})*)\]/g;
  let at = 0;
  for (let m = re.exec(answer); m; m = re.exec(answer)) {
    if (m.index > at) parts.push({ kind: "text", text: answer.slice(at, m.index) });
    for (const raw of m[1].split(",")) {
      const n = Number(raw.trim());
      parts.push({ kind: "cite", n, valid: n >= 1 && n <= sourceCount });
    }
    at = m.index + m[0].length;
  }
  if (at < answer.length) parts.push({ kind: "text", text: answer.slice(at) });
  return parts;
}

export function questionProblem(question: string): string | null {
  const q = question.trim();
  if (q.length < 5) return "Ask a question of at least five characters.";
  if (q.length > 500) return "Keep the question under 500 characters.";
  return null;
}
