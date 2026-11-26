"use client";

/**
 * ChromeWordmark: the footer's closing "StockViz", filled with the same
 * liquid metal as the hero (owner, 26 Nov 2026), so the page opens and
 * closes on one material. The key light follows the pointer.
 *
 * How: the word is drawn white into an off-screen 2D canvas with the
 * element's own font, size and letter-spacing, and that canvas is the mask
 * the shader (`LIQUID_CHROME_MASKED_FRAGMENT`) reads. The outlined text stays
 * on top: it keeps the letter edges crisp, and it is the whole wordmark
 * without WebGL, before the fonts load, or in tests.
 *
 * - Decorative and aria-hidden; pointer events pass through.
 * - Draws only while on screen, at most 1.5x device pixels.
 * - With reduced motion it renders one still frame and never animates.
 */

import { useEffect, useRef } from "react";

import {
  LIQUID_CHROME_MASKED_FRAGMENT,
  LIQUID_CHROME_VERTEX,
} from "@/components/prism/liquid-chrome.glsl";
import { mediaMatches } from "@/lib/media";
import { cn } from "@/lib/utils";

function cssColor(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/** Draw `text` as the element lays it out: same font, centred, same baseline. */
function drawMask(mask: HTMLCanvasElement, text: HTMLElement, ratio: number) {
  const box = text.getBoundingClientRect();
  mask.width = Math.max(1, Math.round(box.width * ratio));
  mask.height = Math.max(1, Math.round(box.height * ratio));
  const ctx = mask.getContext("2d");
  if (!ctx) return;
  const style = getComputedStyle(text);
  const size = Number.parseFloat(style.fontSize) * ratio;
  ctx.clearRect(0, 0, mask.width, mask.height);
  ctx.font = `${style.fontStyle} ${style.fontWeight} ${size}px ${style.fontFamily}`;
  const spacing = Number.parseFloat(style.letterSpacing);
  if ("letterSpacing" in ctx && Number.isFinite(spacing)) {
    (ctx as CanvasRenderingContext2D & { letterSpacing: string }).letterSpacing =
      `${spacing * ratio}px`;
  }
  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#fff";
  const metrics = ctx.measureText(text.textContent ?? "");
  const ascent = metrics.fontBoundingBoxAscent ?? size * 0.8;
  const descent = metrics.fontBoundingBoxDescent ?? size * 0.2;
  // CSS splits the line's leftover height evenly above and below the glyphs.
  const lineHeight = Number.parseFloat(style.lineHeight) * ratio || size;
  const baseline = (lineHeight - (ascent + descent)) / 2 + ascent;
  ctx.fillText(text.textContent ?? "", mask.width / 2, baseline);
}

export function ChromeWordmark({ className }: { className?: string }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLParagraphElement>(null);

  useEffect(() => {
    const host = hostRef.current;
    const text = textRef.current;
    if (!host || !text) return;
    let disposed = false;
    let cleanup = () => {};

    (async () => {
      // Draw the mask only with the real face, or the metal and the outline disagree.
      await document.fonts?.ready;
      const THREE = await import("three");
      if (disposed) return;

      let renderer: import("three").WebGLRenderer;
      try {
        renderer = new THREE.WebGLRenderer({
          alpha: true,
          antialias: true,
          premultipliedAlpha: true,
        });
      } catch {
        return; // No WebGL: the outlined wordmark stands alone.
      }
      const ratio = Math.min(window.devicePixelRatio || 1, 1.5);
      renderer.setPixelRatio(ratio);
      renderer.setClearColor(0x000000, 0);
      const canvas = renderer.domElement;
      canvas.setAttribute("aria-hidden", "true");
      canvas.className = "absolute inset-0 h-full w-full";
      host.prepend(canvas);

      const mask = document.createElement("canvas");
      const texture = new THREE.CanvasTexture(mask);
      texture.minFilter = THREE.LinearFilter;
      texture.magFilter = THREE.LinearFilter;
      const srgb = (css: string) => new THREE.Color(css).convertLinearToSRGB();
      const uniforms = {
        uTime: { value: 20 },
        uRes: { value: new THREE.Vector2(1, 1) },
        uPointer: { value: new THREE.Vector2(0, 0) },
        uSteel: { value: srgb(cssColor("--brand-gradient-from", "#8d9bb0")) },
        uChampagne: { value: srgb(cssColor("--brand-gradient-via", "#f0dfba")) },
        uSilver: { value: srgb(cssColor("--brand-gradient-to", "#d6dbe2")) },
        uMask: { value: texture },
      };
      const material = new THREE.ShaderMaterial({
        vertexShader: LIQUID_CHROME_VERTEX,
        fragmentShader: LIQUID_CHROME_MASKED_FRAGMENT,
        uniforms,
        transparent: true,
        premultipliedAlpha: true,
        depthWrite: false,
      });
      const scene = new THREE.Scene();
      const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      const quad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
      scene.add(quad);

      const resize = () => {
        const w = host.clientWidth || 1;
        const h = host.clientHeight || 1;
        renderer.setSize(w, h, false);
        uniforms.uRes.value.set(w * ratio, h * ratio);
        drawMask(mask, text, ratio);
        texture.needsUpdate = true;
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
        uniforms.uTime.value += Math.min(now - last, 50) / 1000;
        last = now;
        uniforms.uPointer.value.lerp(target, 0.05);
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
        texture.dispose();
        renderer.dispose();
        canvas.remove();
      };
    })();

    return () => {
      disposed = true;
      cleanup();
    };
  }, []);

  return (
    <div ref={hostRef} aria-hidden className={cn("pointer-events-none relative", className)}>
      <p
        ref={textRef}
        className="text-outline relative w-full text-center font-semibold tracking-tight select-none [--outline-color:var(--brand)] text-[clamp(4rem,17vw,15rem)] leading-none"
      >
        StockViz
      </p>
    </div>
  );
}
