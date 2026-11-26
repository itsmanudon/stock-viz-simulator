"use client";

/**
 * LiquidChrome: the hero's and closing CTA's light in the Liquid Chrome look.
 * One full-screen fragment shader (three.js, loaded on demand) that draws a
 * slowly pouring sheet of polished metal in the brand's steel, silver and
 * champagne. The key light follows the pointer. The GLSL is in
 * `liquid-chrome.glsl.ts`.
 *
 * It carries one fact as colour, as PrismField and the Aurora "market
 * weather" did: `share` (the fraction of tracked symbols that closed up at
 * the latest session) tints the mid-tones of the metal toward the gain green
 * above one half and toward the loss red below it. The hero chips and the
 * CTA state that figure as text, so the colour is never the only place it
 * appears.
 *
 * - Decorative and aria-hidden; pointer events pass through.
 * - Draws at 0.6x device pixels (at most 1.5x), and only while on screen.
 * - With reduced motion it renders one still frame and never animates.
 * - Without WebGL it renders nothing; the page's own background shows.
 */

import { useEffect, useRef } from "react";

import {
  LIQUID_CHROME_FRAGMENT,
  LIQUID_CHROME_VERTEX,
} from "@/components/prism/liquid-chrome.glsl";
import { mediaMatches } from "@/lib/media";
import { cn } from "@/lib/utils";

/** Mid-tone tint for a breadth share: 0 at an even split, at most 0.35. */
export function moodAmount(share: number | null | undefined): number {
  if (typeof share !== "number" || Number.isNaN(share)) return 0;
  return Math.min(0.35, Math.abs(share - 0.5) * 0.9);
}

/** Render scale: metal is soft, so a fraction of the device pixels is enough. */
const RENDER_SCALE = 0.6;

function cssColor(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function LiquidChrome({ share, className }: { share?: number | null; className?: string }) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let disposed = false;
    let cleanup = () => {};

    (async () => {
      const THREE = await import("three");
      if (disposed) return;

      let renderer: import("three").WebGLRenderer;
      try {
        renderer = new THREE.WebGLRenderer({
          alpha: true,
          antialias: false,
          premultipliedAlpha: true,
          powerPreference: "low-power",
        });
      } catch {
        return; // No WebGL: the page background carries on alone.
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5) * RENDER_SCALE);
      renderer.setClearColor(0x000000, 0);
      const canvas = renderer.domElement;
      canvas.setAttribute("aria-hidden", "true");
      canvas.style.width = "100%";
      canvas.style.height = "100%";
      canvas.style.display = "block";
      host.appendChild(canvas);

      const scene = new THREE.Scene();
      const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      // Shader uniforms are written straight to the screen, so keep them in
      // sRGB rather than the linear space THREE.Color converts CSS into.
      const srgb = (css: string) => new THREE.Color(css).convertLinearToSRGB();
      const up = typeof share === "number" && share >= 0.5;
      const uniforms = {
        uTime: { value: 8 },
        uRes: { value: new THREE.Vector2(1, 1) },
        uPointer: { value: new THREE.Vector2(0, 0) },
        uSteel: { value: srgb(cssColor("--brand-gradient-from", "#8d9bb0")) },
        uChampagne: { value: srgb(cssColor("--brand-gradient-via", "#f0dfba")) },
        uSilver: { value: srgb(cssColor("--brand-gradient-to", "#d6dbe2")) },
        uMood: {
          value: srgb(up ? cssColor("--positive", "#3ee59a") : cssColor("--negative", "#ff6b7f")),
        },
        uMoodAmount: { value: moodAmount(share) },
      };
      const material = new THREE.ShaderMaterial({
        vertexShader: LIQUID_CHROME_VERTEX,
        fragmentShader: LIQUID_CHROME_FRAGMENT,
        uniforms,
        transparent: true,
        premultipliedAlpha: true,
        depthWrite: false,
      });
      const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
      scene.add(quad);

      const resize = () => {
        const w = host.clientWidth || 1;
        const h = host.clientHeight || 1;
        renderer.setSize(w, h, false);
        const ratio = renderer.getPixelRatio();
        uniforms.uRes.value.set(w * ratio, h * ratio);
        renderer.render(scene, camera);
      };
      resize();
      const ro = new ResizeObserver(resize);
      ro.observe(host);

      const reduced = mediaMatches("(prefers-reduced-motion: reduce)");
      let frame = 0;
      let visible = false;
      let last = performance.now();
      const target = new THREE.Vector2(0, 0);

      const onPointer = (event: PointerEvent) => {
        const rect = host.getBoundingClientRect();
        target.set(
          (event.clientX - rect.left) / rect.width - 0.5,
          0.5 - (event.clientY - rect.top) / rect.height,
        );
      };

      const tick = (now: number) => {
        // Advance by elapsed time, capped, so a backgrounded tab resumes
        // where it left off instead of jumping.
        uniforms.uTime.value += Math.min(now - last, 50) / 1000;
        last = now;
        uniforms.uPointer.value.lerp(target, 0.04);
        renderer.render(scene, camera);
        frame = requestAnimationFrame(tick);
      };

      let io: IntersectionObserver | null = null;
      if (!reduced) {
        window.addEventListener("pointermove", onPointer, { passive: true });
        io = new IntersectionObserver(([entry]) => {
          if (entry.isIntersecting && !visible) {
            visible = true;
            last = performance.now();
            frame = requestAnimationFrame(tick);
          } else if (!entry.isIntersecting && visible) {
            visible = false;
            cancelAnimationFrame(frame);
          }
        });
        io.observe(host);
      }

      cleanup = () => {
        cancelAnimationFrame(frame);
        io?.disconnect();
        ro.disconnect();
        window.removeEventListener("pointermove", onPointer);
        quad.geometry.dispose();
        material.dispose();
        renderer.dispose();
        canvas.remove();
      };
    })();

    return () => {
      disposed = true;
      cleanup();
    };
  }, [share]);

  return (
    <div
      ref={hostRef}
      aria-hidden
      className={cn(
        "pointer-events-none absolute -z-10 [mask-image:linear-gradient(black_70%,transparent)]",
        className,
      )}
    />
  );
}
