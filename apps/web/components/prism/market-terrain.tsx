"use client";

/**
 * Market terrain: the landing page's "fourth dimension" section.
 *
 * Three axes are space: sessions run left to right, symbols run front to
 * back (ordered from the window's biggest loser to its biggest gainer), and
 * height is each symbol's change since the window's first stored close. The
 * fourth axis is time: scrolling through the section moves a light front
 * across the sessions. Everything behind the front is raised to its real
 * height; everything ahead of it lies flat under a haze, because the future
 * is not known yet (the same rule as Replay Lab).
 *
 * - Under the surface, one sentence states the session in view, how many
 *   symbols were above their starting close and the leader and laggard, its
 *   digits rolling as time moves (landing; the dashboard tile keeps its stat
 *   panel). The canvas (aria-hidden) is never the only place a figure appears.
 * - Time is a full-width rail: a real range input with the session's date on
 *   its thumb and the months marked under it, so the same scrub works from a
 *   keyboard and a screen reader; dragging it scrolls the page to match.
 * - Reduced motion: no tall scroll track, no camera drift; the slider alone
 *   moves time and the surface opens on the latest session.
 * - Without WebGL the surface falls back to a 2D heat map of the same grid.
 * - With sound on, the front ticks every ten sessions.
 */

import Link from "next/link";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { RollingText } from "@/components/prism/rolling-text";
import { emitSound } from "@/components/sound/sound-provider";
import { cn } from "@/lib/utils";

import { mediaMatches } from "@/lib/media";
import type { TerrainData } from "./terrain-data";

const VERTEX = /* glsl */ `
  attribute float aRet;
  attribute float aDay;
  uniform float uProgress;
  uniform float uScale;
  uniform float uTime;
  varying float vRet;
  varying float vDay;
  varying float vAhead;
  varying vec2 vGrid;

  void main() {
    vRet = aRet;
    vDay = aDay;
    // How far past the time front this vertex is (0 = at or behind it).
    float ahead = smoothstep(0.0, 0.035, aDay - uProgress);
    vAhead = ahead;
    vec3 p = position;
    // Compressed so one runaway symbol does not flatten into a plateau.
    float height = sign(aRet) * pow(clamp(abs(aRet) / 120.0, 0.0, 1.0), 0.55) * uScale;
    // A soft swell rides the front, so time arriving reads as motion.
    float swell = exp(-pow((aDay - uProgress) * 28.0, 2.0)) * 0.22;
    p.y = mix(height, -0.02 + sin(p.x * 1.7 + uTime) * 0.015, ahead) + swell;
    vGrid = vec2(position.x, position.z);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }
`;

const FRAGMENT = /* glsl */ `
  precision highp float;
  uniform float uProgress;
  uniform vec3 uUp;
  uniform vec3 uDown;
  uniform vec3 uFlat;
  uniform vec3 uFront;
  uniform vec2 uCells;
  varying float vRet;
  varying float vDay;
  varying float vAhead;
  varying vec2 vGrid;

  void main() {
    // Wire grid: one line per session column and per symbol row.
    vec2 cell = vGrid * uCells;
    vec2 g = abs(fract(cell - 0.5) - 0.5) / fwidth(cell);
    float line = 1.0 - min(min(g.x, g.y), 1.0);

    float k = clamp(abs(vRet) / 30.0, 0.0, 1.0);
    vec3 tone = vRet >= 0.0 ? uUp : uDown;
    vec3 base = mix(uFlat, tone, 0.25 + 0.75 * k);

    float front = exp(-pow((vDay - uProgress) * 60.0, 2.0));
    vec3 col = base * (0.35 + 0.65 * line) + uFront * front * 1.4;

    // The future: flat, dim, hazy.
    col = mix(col, uFlat * (0.25 + 0.5 * line), vAhead);
    float alpha = mix(0.55 + 0.45 * line, 0.18 + 0.3 * line, vAhead);
    gl_FragColor = vec4(col, alpha);
  }
`;

type Stats = {
  index: number;
  above: number;
  leader: { ticker: string; value: number };
  laggard: { ticker: string; value: number };
};

function statsAt(data: TerrainData, index: number): Stats {
  let above = 0;
  let leader = { ticker: data.tickers[0], value: Number.NEGATIVE_INFINITY };
  let laggard = { ticker: data.tickers[0], value: Number.POSITIVE_INFINITY };
  data.series.forEach((row, i) => {
    const v = row[index] ?? 0;
    if (v > 0) above += 1;
    if (v > leader.value) leader = { ticker: data.tickers[i], value: v };
    if (v < laggard.value) laggard = { ticker: data.tickers[i], value: v };
  });
  return { index, above, leader, laggard };
}

function pct(v: number) {
  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
}

/** "+21.66%" / "−22.52%" with a real minus sign, for the sentence. */
function signedPct(v: number) {
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}%`;
}

/** Thumb centre on an 18px-thumb range input, as a CSS `left`. */
function onTrack(fraction: number) {
  return `calc(${fraction * 100}% + ${(0.5 - fraction) * 18}px)`;
}

function cssColor(name: string, fallback: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function MarketTerrain({
  data,
  variant = "scroll",
  href,
}: {
  data: TerrainData;
  /**
   * `scroll`: the landing section, pinned while scrolling moves time.
   * `compact`: a dashboard tile; time plays on its own while the tile is on
   * screen (motion allowed) until the slider is touched.
   */
  variant?: "scroll" | "compact";
  /** Compact only: where the tile's heading links. */
  href?: string;
}) {
  const compact = variant === "compact";
  const headingId = useId();
  const userMoved = useRef(false);
  const sectionRef = useRef<HTMLElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const progressRef = useRef(1);
  const [reduced, setReduced] = useState(false);
  const [index, setIndex] = useState(data.sessions - 1);
  const lastTick = useRef(data.sessions - 1);
  const redrawRef = useRef<(() => void) | null>(null);

  const stats = useMemo(() => statsAt(data, index), [data, index]);
  const sessionsBack = data.sessions - 1 - index;
  // The first session of each month after the first, for the rail's marks.
  const months = useMemo(() => {
    const out: [string, number][] = [];
    data.dates?.forEach((date, i) => {
      const month = date.slice(0, 3);
      if (i > 0 && month !== data.dates?.[i - 1].slice(0, 3)) out.push([month, i]);
    });
    return out;
  }, [data.dates]);

  const applyProgress = useCallback(
    (p: number) => {
      const clamped = Math.min(1, Math.max(0, p));
      progressRef.current = clamped;
      const next = Math.round(clamped * (data.sessions - 1));
      setIndex(next);
      if (Math.floor(next / 10) !== Math.floor(lastTick.current / 10)) emitSound("tick");
      lastTick.current = next;
      redrawRef.current?.();
    },
    [data.sessions],
  );

  // Scroll drives time (motion allowed only).
  useEffect(() => {
    const reducedNow = mediaMatches("(prefers-reduced-motion: reduce)");
    setReduced(reducedNow);
    if (reducedNow || compact) return;
    progressRef.current = 0.02;
    setIndex(Math.round(0.02 * (data.sessions - 1)));
    const onScroll = () => {
      const section = sectionRef.current;
      if (!section) return;
      const rect = section.getBoundingClientRect();
      const track = rect.height - window.innerHeight;
      if (track <= 0) return;
      // The front starts moving once the stage is pinned and reaches the
      // latest session a little before the pin releases.
      applyProgress((-rect.top / track) * 1.08);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [applyProgress, data.sessions, compact]);

  // Compact tile: time plays by itself while on screen, then holds on the
  // latest session for a beat and starts again. Stops for good once the
  // slider is used. Never with reduced motion.
  useEffect(() => {
    if (!compact) return;
    const section = sectionRef.current;
    if (!section || mediaMatches("(prefers-reduced-motion: reduce)")) return;
    const PLAY = 14000;
    const HOLD = 4000;
    let frame = 0;
    let start = 0;
    const loop = (now: number) => {
      if (userMoved.current) return;
      if (!start) start = now;
      const t = (now - start) % (PLAY + HOLD);
      applyProgress(Math.min(1, t / PLAY));
      frame = requestAnimationFrame(loop);
    };
    const io = new IntersectionObserver(([entry]) => {
      cancelAnimationFrame(frame);
      if (entry.isIntersecting && !userMoved.current) frame = requestAnimationFrame(loop);
    });
    io.observe(section);
    return () => {
      io.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [compact, applyProgress]);

  // The surface itself.
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
          antialias: true,
          alpha: true,
          powerPreference: "high-performance",
        });
      } catch {
        cleanup = drawFallback(host, data);
        return;
      }
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
      renderer.setClearColor(0x000000, 0);
      const canvas = renderer.domElement;
      canvas.setAttribute("aria-hidden", "true");
      canvas.style.width = "100%";
      canvas.style.height = "100%";
      canvas.style.display = "block";
      host.appendChild(canvas);

      const rows = data.series.length;
      const cols = data.sessions;
      const width = 16;
      const depth = Math.max(6, rows * 0.42);
      const geometry = new THREE.PlaneGeometry(width, depth, cols - 1, rows - 1);
      geometry.rotateX(-Math.PI / 2);
      const count = cols * rows;
      const ret = new Float32Array(count);
      const day = new Float32Array(count);
      // PlaneGeometry orders vertices row by row (along x), front row last
      // after the rotation; row 0 is the back.
      for (let r = 0; r < rows; r++) {
        const series = data.series[rows - 1 - r];
        for (let c = 0; c < cols; c++) {
          const i = r * cols + c;
          ret[i] = series[c] ?? 0;
          day[i] = c / (cols - 1);
        }
      }
      geometry.setAttribute("aRet", new THREE.BufferAttribute(ret, 1));
      geometry.setAttribute("aDay", new THREE.BufferAttribute(day, 1));

      const srgb = (css: string) => new THREE.Color(css).convertLinearToSRGB();
      const uniforms = {
        uProgress: { value: progressRef.current },
        uScale: { value: 3.4 },
        uTime: { value: 0 },
        uUp: { value: srgb(cssColor("--positive", "#3ee59a")) },
        uDown: { value: srgb(cssColor("--negative", "#ff6b7f")) },
        uFlat: { value: srgb(cssColor("--brand-gradient-from", "#8d9bb0")) },
        uFront: { value: srgb(cssColor("--brand-gradient-via", "#f0dfba")) },
        uCells: { value: new THREE.Vector2((cols - 1) / width, (rows - 1) / depth) },
      };
      const material = new THREE.ShaderMaterial({
        vertexShader: VERTEX,
        fragmentShader: FRAGMENT,
        uniforms,
        transparent: true,
        side: THREE.DoubleSide,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      });
      const mesh = new THREE.Mesh(geometry, material);

      const scene = new THREE.Scene();
      scene.add(mesh);

      // A faint floor grid gives the surface something to stand on.
      const floor = new THREE.GridHelper(26, 26, 0x2a2840, 0x15141f);
      floor.position.y = -2.9;
      (floor.material as import("three").Material).transparent = true;
      (floor.material as import("three").Material).opacity = 0.6;
      scene.add(floor);

      const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
      const look = new THREE.Vector3(0, -0.2, 0);

      const resize = () => {
        const w = host.clientWidth || 1;
        const h = host.clientHeight || 1;
        renderer.setSize(w, h, false);
        camera.aspect = w / h;
        // Pull back on narrow screens so the whole surface fits.
        const narrow = w / h < 1 || compact;
        camera.fov = narrow ? 52 : 38;
        // Push the surface right and down, clear of the heading and the
        // stats panel (wide screens); on narrow ones only down.
        camera.setViewOffset(
          w,
          h,
          compact ? -w * 0.1 : narrow ? 0 : -w * 0.16,
          compact ? h * 0.04 : -h * (narrow ? 0.02 : 0.06),
          w,
          h,
        );
        camera.updateProjectionMatrix();
        redrawRef.current?.();
      };
      resize();
      const ro = new ResizeObserver(resize);
      ro.observe(host);

      const reducedMotion = mediaMatches("(prefers-reduced-motion: reduce)");
      const pointer = { x: 0, y: 0 };
      const eased = { x: 0, y: 0, p: progressRef.current };
      const onPointer = (event: PointerEvent) => {
        const rect = host.getBoundingClientRect();
        pointer.x = ((event.clientX - rect.left) / rect.width - 0.5) * 2;
        pointer.y = ((event.clientY - rect.top) / rect.height - 0.5) * 2;
      };

      const place = (p: number, px: number, py: number) => {
        // Orbit from a low three-quarter view to a higher one as time passes.
        const angle = -0.55 + p * 0.75 + px * 0.12;
        const radius = compact ? 12.5 : 15.5;
        camera.position.set(
          Math.sin(angle) * radius,
          5.2 + p * 2.2 - py * 0.8,
          Math.cos(angle) * radius,
        );
        camera.lookAt(look);
      };

      let frame = 0;
      let visible = false;
      const start = performance.now();
      const render = () => {
        uniforms.uProgress.value = eased.p;
        renderer.render(scene, camera);
      };

      if (reducedMotion) {
        // No loop at all: one still frame now, and one each time the slider
        // moves (applyProgress calls redrawRef).
        place(0.75, 0, 0);
        redrawRef.current = () => {
          eased.p = progressRef.current;
          render();
        };
        redrawRef.current();
      } else {
        window.addEventListener("pointermove", onPointer, { passive: true });
        const tick = (now: number) => {
          eased.x += (pointer.x - eased.x) * 0.05;
          eased.y += (pointer.y - eased.y) * 0.05;
          eased.p += (progressRef.current - eased.p) * 0.12;
          uniforms.uTime.value = (now - start) / 1000;
          place(eased.p, eased.x, eased.y);
          render();
          frame = requestAnimationFrame(tick);
        };
        const io = new IntersectionObserver(([entry]) => {
          if (entry.isIntersecting && !visible) {
            visible = true;
            frame = requestAnimationFrame(tick);
          } else if (!entry.isIntersecting && visible) {
            visible = false;
            cancelAnimationFrame(frame);
          }
        });
        io.observe(host);
        const prev = cleanup;
        cleanup = () => {
          prev();
          io.disconnect();
        };
      }

      const prev = cleanup;
      cleanup = () => {
        prev();
        redrawRef.current = null;
        cancelAnimationFrame(frame);
        ro.disconnect();
        window.removeEventListener("pointermove", onPointer);
        geometry.dispose();
        material.dispose();
        floor.geometry.dispose();
        renderer.dispose();
        canvas.remove();
      };
    })();

    return () => {
      disposed = true;
      cleanup();
    };
  }, [data, compact]);

  const onSlide = (value: number) => {
    const p = value / (data.sessions - 1);
    const section = sectionRef.current;
    userMoved.current = true;
    if (!reduced && !compact && section) {
      // Keep one source of truth: move the page to where this session sits.
      const rect = section.getBoundingClientRect();
      const track = rect.height - window.innerHeight;
      const top = window.scrollY + rect.top;
      window.scrollTo({ top: top + (p / 1.08) * track, behavior: "instant" as ScrollBehavior });
    }
    applyProgress(p);
  };

  const label =
    sessionsBack === 0
      ? `Latest stored session${data.lastDate ? `, ${data.lastDate}` : ""}`
      : `${sessionsBack} ${sessionsBack === 1 ? "session" : "sessions"} before ${data.lastDate ?? "the latest close"}`;

  const when = data.dates?.[index] ?? (sessionsBack === 0 ? data.lastDate : null);
  const fraction = index / (data.sessions - 1);

  // The window's first session: every row is rebased to it, so all sit at
  // zero and a leader and laggard would be arbitrary.
  const sentence =
    index === 0 ? (
      <p className="max-w-4xl text-2xl leading-snug font-medium tracking-[-0.025em] text-balance [text-shadow:0_0_24px_var(--background),0_0_8px_var(--background)] sm:text-4xl sm:leading-tight">
        {when ? <>On {when}, all</> : "All"} {data.tickers.length} start level at 0.00%: the
        window&rsquo;s first close.
      </p>
    ) : (
      <p className="max-w-4xl text-2xl leading-snug font-medium tracking-[-0.025em] text-balance [text-shadow:0_0_24px_var(--background),0_0_8px_var(--background)] sm:text-4xl sm:leading-tight">
        {when ? (
          <>
            On <RollingText value={when} />,{" "}
          </>
        ) : (
          <>{label}, </>
        )}
        <RollingText value={String(stats.above)} /> of {data.tickers.length}{" "}
        {stats.above === 1 ? "was" : "were"} above where they started.{" "}
        <span className="ticker">{stats.leader.ticker}</span> led at{" "}
        <RollingText
          value={signedPct(stats.leader.value)}
          className={stats.leader.value >= 0 ? "text-positive" : "text-negative"}
        />
        ; <span className="ticker">{stats.laggard.ticker}</span> trailed at{" "}
        <RollingText
          value={signedPct(stats.laggard.value)}
          className={stats.laggard.value >= 0 ? "text-positive" : "text-negative"}
        />
        .
      </p>
    );

  const rail = (
    <div className="relative pt-12">
      <span
        aria-hidden
        className="glass absolute top-0 rounded-full px-3 py-1.5 font-mono text-sm whitespace-nowrap tabular-nums"
        style={{ left: onTrack(fraction), transform: `translateX(-${fraction * 100}%)` }}
      >
        {when ?? `${index + 1} of ${data.sessions}`}
      </span>
      <input
        type="range"
        min={0}
        max={data.sessions - 1}
        step={1}
        value={index}
        onChange={(event) => onSlide(Number(event.target.value))}
        aria-label="Move through time"
        aria-valuetext={when ?? label}
        data-sound="none"
        className="prism-range w-full"
      />
      {months.length ? (
        <div aria-hidden className="relative mt-1 h-7">
          {months.map(([month, at]) => (
            <span
              key={at}
              className="absolute top-0 flex -translate-x-1/2 flex-col items-center gap-1 text-sm text-text-tertiary"
              style={{ left: onTrack(at / (data.sessions - 1)) }}
            >
              <span className="h-1.5 w-px bg-border" />
              {month}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );

  const statsPanel = (
    <dl
      className={cn(
        "glass grid grid-cols-2 gap-x-6 gap-y-3 rounded-2xl",
        compact ? "p-3 sm:grid-cols-4" : "p-4 sm:grid-cols-4 sm:p-5",
      )}
    >
      <div className="col-span-2 sm:col-span-4">
        <dt className="sr-only">Session in view</dt>
        <dd className="font-mono text-xs text-text-secondary">{label}</dd>
      </div>
      <div>
        <dt className="text-2xs text-text-tertiary">Above their start</dt>
        <dd
          className={cn(
            "mt-1 font-mono text-foreground tabular-nums",
            compact ? "text-base" : "text-lg",
          )}
        >
          {stats.above}
          <span className="text-text-tertiary"> / {data.tickers.length}</span>
        </dd>
      </div>
      <div>
        <dt className="text-2xs text-text-tertiary">Session</dt>
        <dd
          className={cn(
            "mt-1 font-mono text-foreground tabular-nums",
            compact ? "text-base" : "text-lg",
          )}
        >
          {stats.index + 1}
          <span className="text-text-tertiary"> / {data.sessions}</span>
        </dd>
      </div>
      <div>
        <dt className="text-2xs text-text-tertiary">Leading</dt>
        <dd className="mt-1 font-mono text-sm tabular-nums">
          <span className="ticker font-semibold text-foreground">{stats.leader.ticker}</span>{" "}
          <span className="text-positive">{pct(stats.leader.value)}</span>
        </dd>
      </div>
      <div>
        <dt className="text-2xs text-text-tertiary">Lagging</dt>
        <dd className="mt-1 font-mono text-sm tabular-nums">
          <span className="ticker font-semibold text-foreground">{stats.laggard.ticker}</span>{" "}
          <span className={stats.laggard.value < 0 ? "text-negative" : "text-positive"}>
            {pct(stats.laggard.value)}
          </span>
        </dd>
      </div>
    </dl>
  );

  const slider = (
    <label
      className={cn(
        "glass flex min-w-0 flex-col gap-2 rounded-2xl",
        compact ? "p-3 sm:w-60" : "p-4 sm:w-72 sm:p-5",
      )}
    >
      <span className="flex items-center justify-between text-2xs text-text-tertiary">
        <span>Move through time</span>
        <span className="font-mono">
          {stats.index + 1}/{data.sessions}
        </span>
      </span>
      <input
        type="range"
        min={0}
        max={data.sessions - 1}
        step={1}
        value={index}
        onChange={(event) => onSlide(Number(event.target.value))}
        aria-valuetext={label}
        data-sound="none"
        className="prism-range w-full"
      />
    </label>
  );

  // Faded at the edges with a mask on the canvas itself, not gradient
  // overlays: a DOM layer stacked over a WebGL canvas made some compositors
  // drop the canvas entirely.
  const surface = (
    <div
      ref={hostRef}
      className={cn(
        "absolute inset-0",
        compact
          ? "[mask-image:linear-gradient(transparent,black_12%,black_80%,transparent)]"
          : "[mask-image:linear-gradient(transparent,black_16%,black_68%,transparent_96%)]",
      )}
    />
  );

  if (compact) {
    return (
      <section
        ref={sectionRef}
        aria-labelledby={headingId}
        className="spotlight relative isolate h-[30rem] overflow-hidden rounded-xl border border-border-muted bg-card sm:h-[26rem]"
      >
        {surface}
        <div className="pointer-events-none relative z-10 flex h-full flex-col justify-between p-4 sm:p-5">
          <div className="flex flex-wrap items-start justify-between gap-3 [text-shadow:0_0_18px_var(--card)]">
            <div className="max-w-sm">
              <h2 id={headingId} className="text-sm font-semibold">
                Market terrain
              </h2>
              <p className="mt-1 text-xs leading-5 text-text-secondary">
                {data.tickers.length} tracked symbols over {data.sessions} stored sessions, rebased
                to the first. Ahead of the light is flat: not known yet.
              </p>
            </div>
            {href ? (
              <Link
                href={href}
                className="pointer-events-auto text-xs font-medium text-text-secondary transition-colors hover:text-brand"
              >
                Open markets
              </Link>
            ) : null}
          </div>
          <div className="pointer-events-auto grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
            {statsPanel}
            {slider}
          </div>
        </div>
      </section>
    );
  }

  return (
    <section
      ref={sectionRef}
      aria-labelledby={headingId}
      className={cn("relative border-y border-border-muted", reduced ? "" : "h-[320vh]")}
    >
      <div
        className={cn(
          "overflow-hidden",
          reduced ? "relative h-[100svh] min-h-[44rem]" : "sticky top-0 h-[100svh] min-h-[36rem]",
        )}
      >
        {surface}

        <div className="pointer-events-none relative z-10 mx-auto flex h-full w-full max-w-7xl flex-col justify-between px-4 pt-24 pb-6 sm:px-6 sm:pt-28 sm:pb-10">
          <div className="max-w-xl [text-shadow:0_0_24px_var(--background),0_0_8px_var(--background)]">
            <h2
              id={headingId}
              className="text-4xl font-medium tracking-[-0.035em] text-balance sm:text-6xl"
            >
              Time is the <span className="font-editorial text-prism">fourth</span> axis.
            </h2>
            <p className="mt-4 max-w-md text-base leading-7 text-text-secondary text-pretty">
              {data.tickers.length} tracked symbols over their last {data.sessions} stored sessions,
              rebased to the first. Scroll to move time forward. What lies ahead of the light is
              flat, because nobody knows it yet.
            </p>
          </div>

          <div className="pointer-events-auto grid gap-6 sm:gap-8">
            {sentence}
            {rail}
          </div>
        </div>
      </div>
    </section>
  );
}

/** 2D heat map of the same grid for browsers without WebGL. */
function drawFallback(host: HTMLDivElement, data: TerrainData) {
  const canvas = document.createElement("canvas");
  canvas.setAttribute("aria-hidden", "true");
  canvas.style.width = "100%";
  canvas.style.height = "100%";
  host.appendChild(canvas);
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const w = host.clientWidth;
  const h = host.clientHeight;
  canvas.width = w * ratio;
  canvas.height = h * ratio;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const rows = data.series.length;
    const cellW = (w * ratio) / data.sessions;
    const cellH = (h * ratio * 0.6) / rows;
    const top = h * ratio * 0.3;
    data.series.forEach((row, r) => {
      row.forEach((v, c) => {
        const k = Math.min(1, Math.abs(v) / 30);
        ctx.fillStyle =
          v >= 0 ? `rgba(62,229,154,${0.1 + k * 0.8})` : `rgba(255,107,127,${0.1 + k * 0.8})`;
        ctx.fillRect(c * cellW, top + r * cellH, cellW + 0.5, cellH - 1);
      });
    });
  }
  return () => canvas.remove();
}
