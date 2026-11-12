"use client";

/**
 * Print and stamp: the order-fill proof.
 *
 * An example order prints out of a slot line by line, like a till receipt,
 * and a FILLED stamp lands on it with a small jolt. The receipt prices the
 * order at a real stored close and names that close's date, which is how a
 * paper fill works: at a dated close, not at a live quote. It is labelled as
 * an example, because no visitor placed it.
 */

import { useRef } from "react";

import { lerp, span, useFrameLoop } from "@/components/marketing/proofs/canvas-loop";

export function PrintStamp({
  heading,
  lines,
  stamp,
}: {
  heading: string;
  lines: [string, string][];
  stamp: string;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const paperRef = useRef<HTMLDivElement>(null);
  const stampRef = useRef<HTMLSpanElement>(null);

  useFrameLoop(stageRef, {
    duration: 7.5,
    final: 6,
    draw: (t) => {
      const paper = paperRef.current;
      const mark = stampRef.current;
      if (!paper || !mark) return;
      const full = paper.scrollHeight;
      // The paper feeds in steps, the way a receipt printer advances.
      const fed = Math.floor(span(t, 0.3, 2.8) * 9) / 9;
      const printing = fed > 0 && fed < 1;
      paper.style.height = `${full * fed}px`;
      paper.style.translate = printing ? `${Math.sin(t * 60) * 0.6}px 0` : "0 0";

      const fall = span(t, 3.1, 3.32);
      const since = t - 3.32;
      const scale = fall < 1 ? lerp(2.6, 1, fall * fall) : 1;
      mark.style.opacity = t >= 3.1 ? "1" : "0";
      mark.style.transform = `translate(-50%, -50%) rotate(-11deg) scale(${scale})`;
      mark.style.boxShadow =
        since > 0
          ? `0 0 0 ${since * 24}px color-mix(in oklab, var(--brand-gradient-from) ${Math.max(0, 35 - since * 60)}%, transparent)`
          : "none";
      paper.style.marginTop =
        since > 0 ? `${Math.sin(since * 70) * Math.exp(-since * 9) * 3}px` : "0";
    },
  });

  return (
    <div ref={stageRef} aria-hidden className="absolute inset-0 grid justify-items-center">
      <span className="absolute top-[12%] h-2 w-[min(17rem,70%)] rounded-full bg-surface-secondary shadow-[inset_0_2px_3px_rgb(0_0_0/0.8)]" />
      <div
        ref={paperRef}
        className="absolute top-[calc(12%+4px)] w-[min(15rem,64%)] overflow-hidden rounded-b-md bg-[#eef1f6] px-3.5 font-mono text-xs leading-6 text-[#1a2130] shadow-[0_16px_30px_-14px_rgb(0_0_0)]"
      >
        <p className="flex justify-between gap-3 border-b border-dashed border-[#b7bfcc] pt-2.5 pb-1.5 font-medium">
          {heading}
        </p>
        {lines.map(([label, value]) => (
          <p key={label} className="flex justify-between gap-3 whitespace-nowrap">
            <span className="text-[#5d6678]">{label}</span>
            <span>{value}</span>
          </p>
        ))}
        <span className="block h-3.5" />
      </div>
      <span
        ref={stampRef}
        className="absolute top-[56%] left-1/2 rounded-md border-[3px] border-brand-gradient-from px-3 py-1.5 font-mono text-sm font-semibold tracking-[0.12em] whitespace-nowrap text-brand-gradient-from opacity-0"
      >
        {stamp}
      </span>
    </div>
  );
}
