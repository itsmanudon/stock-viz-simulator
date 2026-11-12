"use client";

/**
 * Departure board: the leaderboard proof.
 *
 * The public rankings flip in like an airport split-flap board, one column
 * after another, then flip over to the same traders ranked by account value.
 * The board is a picture (aria-hidden); the section lists the same rankings
 * as text for assistive technology.
 */

import { useMemo, useRef } from "react";

import { useFrameLoop } from "@/components/marketing/proofs/canvas-loop";
import { cn } from "@/lib/utils";

export type BoardRow = { rank: string; name: string; value: string; tone: "pos" | "neg" | "none" };
export type Board = { title: string; rows: BoardRow[] };

const WIDTHS = [2, 12, 9] as const;
const HOLD = 5.5;
const GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+-.,%$";

function line(row: BoardRow | undefined) {
  if (!row) return " ".repeat(WIDTHS[0] + WIDTHS[1] + WIDTHS[2]);
  const name = row.name.toUpperCase().slice(0, WIDTHS[1]).padEnd(WIDTHS[1], " ");
  return (
    row.rank.padStart(WIDTHS[0], " ") +
    name +
    row.value.slice(0, WIDTHS[2]).padStart(WIDTHS[2], " ")
  );
}

export function DepartureBoard({ boards }: { boards: Board[] }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const titleRef = useRef<HTMLSpanElement>(null);
  const rowCount = Math.max(...boards.map((b) => b.rows.length));
  const lines = useMemo(
    () => boards.map((b) => Array.from({ length: rowCount }, (_, i) => line(b.rows[i]))),
    [boards, rowCount],
  );
  const width = WIDTHS[0] + WIDTHS[1] + WIDTHS[2];

  useFrameLoop(rootRef, {
    duration: HOLD * boards.length,
    final: 2.5,
    draw: (t) => {
      const root = rootRef.current;
      if (!root) return;
      const which = Math.min(boards.length - 1, Math.floor(t / HOLD));
      const since = t - which * HOLD;
      if (titleRef.current) titleRef.current.textContent = boards[which].title;
      const cells = root.querySelectorAll<HTMLSpanElement>("[data-cell]");
      cells.forEach((cell, k) => {
        const r = Math.floor(k / width);
        const col = k % width;
        const target = lines[which][r][col];
        const start = 0.15 + col * 0.045 + r * 0.07;
        const end = start + 0.42;
        // The very first board flips in from blank; later boards flip from the last.
        if (which === 0 && since < start) {
          cell.textContent = "";
          cell.style.transform = "";
        } else if (since >= start && since < end) {
          cell.textContent = GLYPHS[(Math.floor(t * 28) + col * 7 + r * 3) % GLYPHS.length];
          const phase = ((since - start) * 28) % 1;
          cell.style.transform = `scaleY(${0.35 + 0.65 * Math.abs(Math.cos(phase * Math.PI))})`;
        } else if (since >= end) {
          cell.textContent = target === " " ? "" : target;
          cell.style.transform = "";
        }
        const tone =
          col >= WIDTHS[0] + WIDTHS[1] && since >= end ? boards[which].rows[r]?.tone : "none";
        cell.dataset.tone = tone ?? "none";
      });
    },
  });

  return (
    <div
      ref={rootRef}
      aria-hidden
      className="absolute inset-0 grid content-center gap-1.5 overflow-hidden px-2 py-4 sm:px-4"
    >
      <div className="flex justify-between px-0.5 pb-1 font-mono text-3xs tracking-[0.12em] text-warning">
        <span>RANK · TRADER</span>
        <span ref={titleRef}>{boards[0]?.title}</span>
      </div>
      {Array.from({ length: rowCount }, (_, r) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: fixed rows of the board
        <div key={r} className="flex justify-center gap-[2px] sm:gap-[3px]">
          {Array.from({ length: width }, (_, col) => (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: fixed cells of the board
              key={col}
              data-cell
              className={cn(
                "relative grid h-[clamp(1.25rem,4vw,2rem)] w-[clamp(0.45rem,2.5vw,1.3rem)] place-items-center rounded-[3px] bg-linear-to-b from-surface-secondary from-50% to-card to-50% font-mono text-[clamp(0.45rem,1.9vw,1rem)] font-medium text-foreground shadow-[inset_0_0_0_1px_var(--border-muted)] after:absolute after:inset-x-0 after:top-1/2 after:h-px after:bg-background data-[tone=neg]:text-negative data-[tone=pos]:text-positive",
                (col === WIDTHS[0] || col === WIDTHS[0] + WIDTHS[1]) && "ml-1 sm:ml-1.5",
              )}
            />
          ))}
        </div>
      ))}
    </div>
  );
}
