"use client";

/**
 * PrismField: the hero's light. One full-screen fragment shader (three.js,
 * loaded on demand) that draws slow iridescent ribbons of the brand's
 * steel, champagne and silver (liquid chrome), bending toward the pointer.
 *
 * It carries one fact as colour, like the Aurora "market weather" it
 * replaces: `share` (the fraction of tracked symbols that closed up at the
 * latest session) leans the light toward the gain green above one half and
 * toward the loss red below it. The hero chips state that figure as text, so
 * the colour is never the only place it appears.
 *
 * - Decorative and aria-hidden; pointer events pass through.
 * - Renders only while on screen, at most 1.5x device pixels.
 * - With reduced motion it renders one still frame and never animates.
 * - Without WebGL it renders nothing; the page's own background shows.
 */

import { useEffect, useRef } from "react";

import { mediaMatches } from "@/lib/media";
import { cn } from "@/lib/utils";

const VERTEX = /* glsl */ `
  varying vec2 vUv;
  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`;

const FRAGMENT = /* glsl */ `
  precision highp float;
  varying vec2 vUv;
  uniform float uTime;
  uniform vec2 uRes;
  uniform vec2 uPointer;
  uniform vec3 uA;
  uniform vec3 uB;
  uniform vec3 uC;
  uniform vec3 uMood;
  uniform float uMoodAmount;

  // 2D simplex-ish value noise (cheap, smooth enough for light).
  vec2 hash(vec2 p) {
    p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
    return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
  }
  float noise(vec2 p) {
    const float K1 = 0.366025404;
    const float K2 = 0.211324865;
    vec2 i = floor(p + (p.x + p.y) * K1);
    vec2 a = p - i + (i.x + i.y) * K2;
    vec2 o = (a.x > a.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
    vec2 b = a - o + K2;
    vec2 c = a - 1.0 + 2.0 * K2;
    vec3 h = max(0.5 - vec3(dot(a, a), dot(b, b), dot(c, c)), 0.0);
    vec3 n = h * h * h * h * vec3(dot(a, hash(i)), dot(b, hash(i + o)), dot(c, hash(i + 1.0)));
    return dot(n, vec3(70.0));
  }
  float fbm(vec2 p) {
    float f = 0.0;
    float w = 0.5;
    for (int i = 0; i < 4; i++) {
      f += w * noise(p);
      p *= 2.02;
      w *= 0.5;
    }
    return f;
  }

  void main() {
    vec2 uv = vUv;
    vec2 p = (gl_FragCoord.xy - 0.5 * uRes) / uRes.y;
    float t = uTime * 0.045;

    // Pull the field toward the pointer.
    vec2 toPointer = p - uPointer;
    float pull = exp(-dot(toPointer, toPointer) * 3.0);
    p += toPointer * pull * 0.18;

    // Domain-warped ribbons.
    vec2 q = vec2(fbm(p * 0.7 + vec2(0.0, t)), fbm(p * 0.7 + vec2(5.2, -t)));
    vec2 r = vec2(fbm(p * 0.9 + 1.6 * q + vec2(1.7, 9.2) + t), fbm(p * 0.9 + 1.6 * q + vec2(8.3, 2.8) - t));
    float f = fbm(p * 0.8 + 2.0 * r);

    // Thin bright bands where the field crosses its contours: the "prism" edges.
    float bands = smoothstep(0.0, 0.02, abs(sin(f * 9.0 + t * 6.0)) - 0.96) ;
    float edge = 1.0 - smoothstep(0.0, 0.08, abs(fract(f * 3.0 + t) - 0.5));

    vec3 col = mix(uA, uB, smoothstep(-0.4, 0.6, r.x));
    col = mix(col, uC, smoothstep(-0.2, 0.9, q.y + r.y * 0.5));
    col = mix(col, uMood, uMoodAmount * smoothstep(-0.3, 0.7, f));

    float intensity = smoothstep(-0.25, 0.85, f) * 0.85 + edge * 0.25 + bands * 0.15 + pull * 0.25;

    // Fade to the page at the edges and toward the bottom so copy stays legible.
    float vignette = smoothstep(1.25, 0.15, length(p * vec2(0.75, 1.15)));
    float fadeBottom = smoothstep(0.0, 0.45, uv.y);
    float alpha = intensity * vignette * fadeBottom * 0.62;

    gl_FragColor = vec4(col * alpha, alpha);
  }
`;

function cssColor(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function PrismField({ share, className }: { share?: number | null; className?: string }) {
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
          powerPreference: "low-power",
        });
      } catch {
        return; // No WebGL: the page background carries on alone.
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
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
      const moodShare = typeof share === "number" ? share : 0.5;
      const uniforms = {
        uTime: { value: 12 },
        uRes: { value: new THREE.Vector2(1, 1) },
        uPointer: { value: new THREE.Vector2(0.3, 0.1) },
        uA: { value: srgb(cssColor("--brand-gradient-from", "#8d9bb0")) },
        uB: { value: srgb(cssColor("--brand-gradient-via", "#f0dfba")) },
        uC: { value: srgb(cssColor("--brand-gradient-to", "#d6dbe2")) },
        uMood: {
          value: srgb(
            moodShare >= 0.5
              ? cssColor("--positive", "#3ee59a")
              : cssColor("--negative", "#ff6b7f"),
          ),
        },
        uMoodAmount: { value: Math.min(0.55, Math.abs(moodShare - 0.5) * 1.4) },
      };
      const material = new THREE.ShaderMaterial({
        vertexShader: VERTEX,
        fragmentShader: FRAGMENT,
        uniforms,
        transparent: true,
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
      const target = new THREE.Vector2(0.3, 0.1);
      const start = performance.now();

      const onPointer = (event: PointerEvent) => {
        const rect = host.getBoundingClientRect();
        const x = (event.clientX - rect.left - rect.width / 2) / rect.height;
        const y = -(event.clientY - rect.top - rect.height / 2) / rect.height;
        target.set(x, y);
      };

      const tick = (now: number) => {
        uniforms.uTime.value = 12 + (now - start) / 1000;
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
