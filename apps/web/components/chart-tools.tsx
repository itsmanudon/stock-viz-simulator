"use client";

/**
 * The stock chart's own tools (A6.7): the volume profile (M2.9), the price
 * pane's context menu, and plan lines (M2.11), around `ChartWorkbench`.
 *
 * Everything binds to the built chart through `PriceChart`'s `onChartReady`
 * (the price series, the chart group and the drawings under a point), so the
 * chart file only hands its parts over.
 *
 * - **Volume profile:** `?vp=visible|fixed` (the toolbar's switch). Visible:
 *   the bars on screen, fetched again (debounced) as the chart pans or zooms.
 *   Fixed: each `volume_profile` drawing's sessions. The badges and the note
 *   show under the chart.
 * - **Context menu:** right-click, a long press (touch), or the Menu key /
 *   Shift+F10 on the focused chart, at the crosshair.
 * - **Plan lines:** the ticker's open and active plans (`plan-lines.ts`).
 */

import { useSearchParams } from "next/navigation";
import { type ComponentProps, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { createAlertAction } from "@/app/(product)/(authed)/alerts/actions";
import {
  chartPlansAction,
  chartRuleSetupAction,
  createChartPlanAction,
  updatePlanLinesAction,
  volumeProfileAction,
} from "@/app/(product)/stocks/[ticker]/chart-tools-actions";
import {
  ChartContextMenu,
  type ChartMenuItem,
  ChartPlanEditor,
  type PlanEditorValues,
} from "@/components/chart-context-menu";
import { ChartWorkbench } from "@/components/drawings/chart-workbench";
import { PlanLinesController } from "@/components/plan-lines";
import type { PriceChartHandle } from "@/components/price-chart";
import { previewRule } from "@/lib/alert-rules";
import {
  type IntradayTimeframe,
  atrAt,
  drawingLevels,
  drawingRule,
  intradayTimeframe,
  judgedNote,
  nearestStudy,
  planPrefill,
  priceAlertFields,
  priceRule,
  ruleAlertFields,
  studyAlertFields,
  studyRule,
  toFormData,
} from "@/lib/chart-menu";
import { useChartPalette } from "@/lib/chart-theme";
import { anchorLogical, sessionDateOf } from "@/lib/drawings/anchor";
import { roundPrice } from "@/lib/drawings/drag";
import { kindSpec } from "@/lib/drawings/kinds";
import type { SceneDrawing } from "@/lib/drawings/scene";
import { type ProfileLayer, VolumeProfilePrimitive } from "@/lib/drawings/volume-profile-primitive";
import type { TradePlan } from "@/lib/plans";
import {
  PROFILE_BINS,
  PROFILE_DEBOUNCE_MS,
  PROFILE_PARAM,
  type VolumeProfile,
  debounce,
  parseProfileMode,
  profileCaption,
  rangeOfBars,
  rangeOfSessions,
} from "@/lib/volume-profile";

type Props = ComponentProps<typeof ChartWorkbench> & {
  /** An index's volume is not real: no profile is offered. */
  isIndex?: boolean;
};

const LONG_PRESS_MS = 550;
const LONG_PRESS_SLOP_PX = 8;

type MenuState = {
  left: number;
  top: number;
  price: number;
  index: number;
  y: number;
  drawing: SceneDrawing | null;
  streaming: boolean;
};

function fixedKey(d: SceneDrawing): string | null {
  const [a, b] = d.points.map((p) => p.ts);
  return a && b ? `${a}:${b}` : null;
}

export function ChartWithTools({ isIndex = false, ...workbench }: Props) {
  const { ticker, signedIn, callbackUrl } = workbench;
  const search = useSearchParams();
  const mode = isIndex ? "off" : parseProfileMode(search.get(PROFILE_PARAM));
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const palette = useChartPalette();
  const colours = useMemo(
    () => ({
      bins: palette.drawing.slate,
      value: palette.drawing.blue,
      poc: palette.drawing.amber,
      levels: palette.text,
    }),
    [palette],
  );
  const coloursRef = useRef(colours);
  coloursRef.current = colours;

  const handleRef = useRef<PriceChartHandle | null>(null);
  const primitiveRef = useRef<VolumeProfilePrimitive | null>(null);
  const linesRef = useRef<PlanLinesController | null>(null);
  const lastPointRef = useRef<{ x: number; y: number } | null>(null);

  const [visibleProfile, setVisibleProfile] = useState<VolumeProfile | null>(null);
  const visibleRef = useRef<VolumeProfile | null>(null);
  visibleRef.current = visibleProfile;
  const fixedRef = useRef(new Map<string, VolumeProfile | "loading" | { error: string }>());
  const [fixedShown, setFixedShown] = useState<VolumeProfile[]>([]);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [plans, setPlans] = useState<TradePlan[]>([]);
  const plansRef = useRef(plans);
  plansRef.current = plans;
  const [menu, setMenu] = useState<MenuState | null>(null);
  const [planEditor, setPlanEditor] = useState<PlanEditorValues | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const bars = workbench.bars;
  const lastClose = Number(bars.at(-1)?.close ?? 0);
  const overlays = workbench.overlays;
  const interval = workbench.interval ?? "1d";
  const barDates = useMemo(() => bars.map(sessionDateOf), [bars]);
  const intervalRef = useRef({ interval, barDates });
  intervalRef.current = { interval, barDates };

  // ---- Volume profile ----
  const layersRef = useRef<() => ProfileLayer[]>(() => []);
  const refreshPrimitive = useCallback(() => {
    primitiveRef.current?.setLayers(layersRef.current(), coloursRef.current);
  }, []);

  /** The layers to draw now; a fixed range without its profile yet is fetched. */
  const layersNow = useCallback((): ProfileLayer[] => {
    const layers: ProfileLayer[] = [];
    const current = modeRef.current;
    if (current === "visible" && visibleRef.current) {
      layers.push({ key: "visible", profile: visibleRef.current, placement: { kind: "right" } });
    }
    if (current !== "fixed") return layers;
    const { interval: iv, barDates: dates } = intervalRef.current;
    for (const d of handleRef.current?.drawings() ?? []) {
      if (d.kind !== "volume_profile" || d.id === "draft") continue;
      const key = fixedKey(d);
      if (!key) continue;
      const [a, b] = key.split(":");
      const cached = fixedRef.current.get(key);
      if (cached === undefined) {
        fixedRef.current.set(key, "loading");
        void volumeProfileAction(ticker, { ...rangeOfSessions(a, b), bins: PROFILE_BINS }).then(
          (result) => {
            fixedRef.current.set(key, result.profile ?? { error: result.error ?? "No profile." });
            if (result.error) setProfileError(result.error);
            setFixedShown(
              [...fixedRef.current.values()].filter(
                (v): v is VolumeProfile => typeof v === "object" && "bins" in v,
              ),
            );
            refreshPrimitive();
          },
        );
        continue;
      }
      if (typeof cached !== "object" || !("bins" in cached)) continue;
      const from = anchorLogical(a, iv, dates);
      const to = anchorLogical(b, iv, dates);
      if (from === null || to === null) continue;
      // The last session's last bar: the anchor maps to a session's first bar.
      const last = Math.max(from, to);
      let end = last;
      while (end + 1 < dates.length && dates[end + 1] === dates[last]) end += 1;
      layers.push({
        key: d.id,
        profile: cached,
        placement: { kind: "span", from: Math.min(from, to), to: end },
      });
    }
    return layers;
  }, [ticker, refreshPrimitive]);
  layersRef.current = layersNow;

  const fetchVisible = useMemo(
    () =>
      debounce((from: number, to: number) => {
        const range = rangeOfBars(handleRef.current?.bars ?? [], from, to);
        if (!range || modeRef.current !== "visible") return;
        void volumeProfileAction(ticker, { ...range, bins: PROFILE_BINS }).then((result) => {
          if (modeRef.current !== "visible") return;
          setProfileError(result.error ?? null);
          setVisibleProfile(result.profile ?? null);
        });
      }, PROFILE_DEBOUNCE_MS),
    [ticker],
  );

  const requestVisible = useCallback(() => {
    const chart = handleRef.current?.chart;
    const range = chart?.timeScale().getVisibleLogicalRange();
    const count = handleRef.current?.bars.length ?? 0;
    if (count === 0) return;
    fetchVisible(range ? range.from : 0, range ? range.to : count - 1);
  }, [fetchVisible]);

  useEffect(() => {
    setProfileError(null);
    if (mode === "visible") requestVisible();
    else fetchVisible.cancel();
  }, [mode, requestVisible, fetchVisible]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: a new profile, mode or theme is drawn again.
  useEffect(() => {
    refreshPrimitive();
  }, [mode, refreshPrimitive, visibleProfile, fixedShown, colours]);
  useEffect(() => () => fetchVisible.cancel(), [fetchVisible]);

  // ---- Plans ----
  useEffect(() => {
    if (!signedIn) return;
    let live = true;
    void chartPlansAction(ticker).then((result) => {
      if (live && result.plans) setPlans(result.plans);
    });
    return () => {
      live = false;
    };
  }, [signedIn, ticker]);
  // The lines' own changes (a drag, a save) are already drawn; only plans
  // from elsewhere (the load, a new plan) are handed to them.
  const fromLinesRef = useRef(false);
  useEffect(() => {
    if (fromLinesRef.current) {
      fromLinesRef.current = false;
      return;
    }
    linesRef.current?.setPlans(plans);
  }, [plans]);

  // ---- The chart's parts ----
  const openMenuAt = useCallback((clientX: number, clientY: number, x: number, y: number) => {
    const handle = handleRef.current;
    if (!handle) return;
    const price = handle.series.coordinateToPrice(y);
    const logical = handle.chart.timeScale().coordinateToLogical(x);
    if (price === null || logical === null) return;
    const index = Math.max(0, Math.min(handle.bars.length - 1, Math.round(logical)));
    setMenu({
      left: clientX,
      top: clientY,
      price,
      index,
      y,
      drawing: handle.drawingAt(x, y),
      streaming: handle.streaming(),
    });
  }, []);

  const onChartReady = useCallback(
    (handle: PriceChartHandle) => {
      handleRef.current = handle;
      const primitive = new VolumeProfilePrimitive(coloursRef.current, () => layersRef.current());
      handle.series.attachPrimitive(primitive);
      primitiveRef.current = primitive;
      primitive.setLayers(layersNow());
      const lines = signedIn
        ? new PlanLinesController({
            series: handle.series,
            root: handle.root,
            container: handle.container,
            colours: {
              entry: palette.drawing.blue,
              stop: palette.negative,
              target: palette.positive,
            },
            save: (id, prices) => updatePlanLinesAction(id, prices),
            onPlans: (next) => {
              fromLinesRef.current = true;
              setPlans(next);
            },
            onMessage: setMessage,
          })
        : null;
      lines?.setPlans(plansRef.current);
      linesRef.current = lines;

      const timeScale = handle.chart.timeScale();
      const onRange = () => {
        if (modeRef.current === "visible") requestVisible();
        primitive.setLayers(layersNow());
      };
      timeScale.subscribeVisibleLogicalRangeChange?.(onRange);
      const onCross = (param: { point?: { x: number; y: number } }) => {
        if (param.point) lastPointRef.current = { x: param.point.x, y: param.point.y };
      };
      handle.chart.subscribeCrosshairMove(onCross);

      const pane = (clientX: number, clientY: number) => {
        const rect = handle.container.getBoundingClientRect();
        const x = clientX - rect.left;
        const y = clientY - rect.top;
        const height = handle.chart.panes()[0]?.getHeight() ?? 0;
        const width = timeScale.width();
        return x >= 0 && y >= 0 && x <= width && y <= height ? { x, y } : null;
      };
      const onContextMenu = (event: MouseEvent) => {
        const at = pane(event.clientX, event.clientY);
        if (!at) return;
        event.preventDefault();
        openMenuAt(event.clientX, event.clientY, at.x, at.y);
      };
      let press: { timer: ReturnType<typeof setTimeout>; x: number; y: number } | null = null;
      const cancelPress = () => {
        if (press) clearTimeout(press.timer);
        press = null;
      };
      const onDown = (event: PointerEvent) => {
        if (event.pointerType !== "touch") return;
        const at = pane(event.clientX, event.clientY);
        if (!at) return;
        cancelPress();
        const { clientX, clientY } = event;
        press = {
          x: clientX,
          y: clientY,
          timer: setTimeout(() => {
            press = null;
            openMenuAt(clientX, clientY, at.x, at.y);
          }, LONG_PRESS_MS),
        };
      };
      const onMove = (event: PointerEvent) => {
        if (
          press &&
          Math.hypot(event.clientX - press.x, event.clientY - press.y) > LONG_PRESS_SLOP_PX
        )
          cancelPress();
      };
      const onKey = (event: KeyboardEvent) => {
        if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) return;
        event.preventDefault();
        const rect = handle.container.getBoundingClientRect();
        const point = lastPointRef.current ?? {
          x: timeScale.width() - 40,
          y: handle.series.priceToCoordinate(Number(handle.bars.at(-1)?.close ?? 0)) ?? 40,
        };
        openMenuAt(rect.left + point.x, rect.top + point.y, point.x, point.y);
      };
      const root = handle.root;
      root.addEventListener("contextmenu", onContextMenu);
      root.addEventListener("pointerdown", onDown);
      root.addEventListener("pointermove", onMove);
      root.addEventListener("pointerup", cancelPress);
      root.addEventListener("pointercancel", cancelPress);
      root.addEventListener("keydown", onKey);
      return () => {
        cancelPress();
        root.removeEventListener("contextmenu", onContextMenu);
        root.removeEventListener("pointerdown", onDown);
        root.removeEventListener("pointermove", onMove);
        root.removeEventListener("pointerup", cancelPress);
        root.removeEventListener("pointercancel", cancelPress);
        root.removeEventListener("keydown", onKey);
        timeScale.unsubscribeVisibleLogicalRangeChange?.(onRange);
        handle.chart.unsubscribeCrosshairMove(onCross);
        lines?.destroy();
        if (linesRef.current === lines) linesRef.current = null;
        try {
          handle.series.detachPrimitive(primitive);
        } catch {
          // the chart is being removed
        }
        if (primitiveRef.current === primitive) primitiveRef.current = null;
        if (handleRef.current === handle) handleRef.current = null;
      };
    },
    [signedIn, palette, layersNow, requestVisible, openMenuAt],
  );

  // ---- The menu's items ----
  const closeMenu = useCallback(() => {
    setMenu(null);
    handleRef.current?.root.focus();
  }, []);

  const createAlert = useCallback(async (fields: Record<string, string>, words: string) => {
    const result = await createAlertAction({}, toFormData(fields));
    setMessage(result.error ? result.error : `Alert set. ${words}`);
  }, []);

  /** Saves `rule` as a setup on `timeframe`, then a rule alert on it. */
  const createRuleAlert = useCallback(
    (
      rule: { rule: string; name: string },
      timeframe: IntradayTimeframe | undefined,
      words: string,
    ) => {
      void chartRuleSetupAction(rule.name, rule.rule, timeframe).then((setup) => {
        if (!setup.versionId) {
          setMessage(setup.error ?? "The rule could not be saved.");
          return;
        }
        void createAlert(ruleAlertFields(ticker, setup.versionId), words);
      });
    },
    [ticker, createAlert],
  );

  const items = useMemo<ChartMenuItem[]>(() => {
    if (!menu) return [];
    const handle = handleRef.current;
    // Owner, 27 Nov 2026: alerts from an intraday chart are intraday rules.
    const tf = intradayTimeframe(interval) ?? undefined;
    const tfWords = tf ? `, judged on each closed ${tf} bar` : "";
    const price = Number(roundPrice(menu.price));
    const priceFields = priceAlertFields(ticker, menu.price, lastClose);
    const priceWords = previewRule({
      kind: "price",
      ticker,
      direction: priceFields.direction as "above" | "below",
      target: priceFields.target_price,
      repeat: "once",
    });
    const drawing = menu.drawing;
    const rule = drawing ? drawingRule(drawing, ticker, lastClose, menu.price) : null;
    const bar = bars[menu.index];
    const study =
      handle && bar && overlays
        ? nearestStudy(overlays, bar.ts, menu.y, (p) => handle.series.priceToCoordinate(p))
        : null;
    const studyFields = study ? studyAlertFields(ticker, study.key, study.value, lastClose) : null;
    return [
      {
        id: "price",
        label: "Alert When Price Crosses Here",
        detail: tf
          ? `When ${ticker} ${priceRule(ticker, menu.price, lastClose).words}, once${tfWords}.`
          : priceWords,
        disabled: null,
        onSelect: () => {
          if (!tf) return void createAlert(priceFields, priceWords);
          const r = priceRule(ticker, menu.price, lastClose);
          createRuleAlert(r, tf, `When ${ticker} ${r.words}, once${tfWords}.`);
        },
      },
      {
        id: "drawing",
        label: "Alert on This Drawing",
        detail:
          rule && "rule" in rule ? `When ${ticker} ${rule.words}, once. Rule: ${rule.rule}` : "",
        disabled: !drawing
          ? "Right-click on a drawing to alert on it."
          : rule && "problem" in rule
            ? rule.problem
            : null,
        onSelect: () => {
          if (!rule || !("rule" in rule)) return;
          // Drawings are read on daily bars only (the DSL's rule), so this
          // stays a daily rule on an intraday chart too.
          createRuleAlert(
            rule,
            undefined,
            `When ${ticker} ${rule.words}, once (saved as the setup "${rule.name}"${tf ? ", judged on daily bars" : ""}).`,
          );
        },
      },
      {
        id: "indicator",
        label: "Alert on This Indicator",
        detail: studyFields
          ? previewRule({
              kind: "technical",
              ticker,
              indicator: "close",
              op: studyFields.op as "above" | "below",
              compareTo: studyFields.compare_to,
              repeat: "once",
            })
          : "",
        disabled: study ? null : "Right-click on a study line on the price pane to alert on it.",
        onSelect: () => {
          if (!studyFields || !study) return;
          const r = tf ? studyRule(ticker, study.key, study.value, lastClose) : null;
          if (tf && r) {
            createRuleAlert(r, tf, `When ${ticker} ${r.words}, once${tfWords}.`);
            return;
          }
          void createAlert(
            studyFields,
            `When ${ticker} closes ${studyFields.op} ${studyFields.compare_to}, judged on daily bars.`,
          );
        },
      },
      {
        id: "plan",
        label: "Plan a Trade Here",
        detail: `A long plan with its entry at ${price}.`,
        disabled: null,
        onSelect: () => {
          const prefill = planPrefill(
            menu.price,
            drawingLevels(handle?.drawings() ?? []),
            atrAt(bars, bars.length - 1),
          );
          setPlanEditor({ ...prefill, size: "", why: "" });
        },
      },
    ];
  }, [menu, ticker, lastClose, bars, overlays, createAlert, createRuleAlert, interval]);

  const savePlan = useCallback(
    async (values: PlanEditorValues): Promise<string | null> => {
      const result = await createChartPlanAction({ ticker, ...values });
      if (!result.plan) return result.error ?? "The plan could not be saved.";
      const plan = result.plan;
      setPlans((list) => [...list, plan]);
      setPlanEditor(null);
      setMessage("Plan saved as a draft. Drag its lines to adjust it until its first fill.");
      return null;
    },
    [ticker],
  );

  const shown =
    mode === "visible"
      ? visibleProfile
        ? [visibleProfile]
        : []
      : mode === "fixed"
        ? fixedShown
        : [];
  const fixedCount =
    workbench.initial?.drawings.filter((d) => d.kind === "volume_profile").length ?? 0;
  const signInHref = `/login?callbackUrl=${encodeURIComponent(callbackUrl)}`;

  return (
    <div className="space-y-2" data-testid="chart-tools" data-profile-mode={mode}>
      <ChartWorkbench {...workbench} onChartReady={onChartReady} />
      {mode !== "off" ? (
        <div
          className="space-y-1 px-1 text-2xs text-text-tertiary"
          data-testid="volume-profile-info"
          aria-live="polite"
        >
          {shown.map((p) => (
            <p
              key={`${p.from}-${p.to}`}
              className="flex flex-wrap items-center gap-1.5"
              data-testid="volume-profile-caption"
            >
              {p.badges.map((badge) => (
                <span
                  key={badge}
                  className="inline-flex h-5 items-center rounded-sm border border-border-muted bg-surface-elevated px-1.5 font-medium text-text-secondary"
                  data-testid="volume-profile-badge"
                >
                  {badge}
                </span>
              ))}
              <span>
                POC {p.poc}, value area ({Math.round(p.value_area * 100)}%) {p.val} to {p.vah}.{" "}
                {p.note}
              </span>
              <span className="sr-only">{profileCaption(p)}</span>
            </p>
          ))}
          {mode === "fixed" && fixedCount === 0 && fixedShown.length === 0 ? (
            <p data-testid="volume-profile-fixed-hint">
              Pick {kindSpec("volume_profile").label} in the drawing tools, then click the first and
              last session.
            </p>
          ) : null}
          {mode === "visible" && !visibleProfile && !profileError ? (
            <p>Loading the volume profile…</p>
          ) : null}
          {profileError ? <p data-testid="volume-profile-error">{profileError}</p> : null}
        </div>
      ) : null}
      {message ? (
        <p
          className="px-1 text-2xs text-text-secondary"
          aria-live="polite"
          data-testid="chart-tools-message"
        >
          {message}
        </p>
      ) : null}
      {planEditor ? (
        <ChartPlanEditor
          ticker={ticker}
          initial={planEditor}
          onSave={savePlan}
          onClose={() => setPlanEditor(null)}
        />
      ) : null}
      {menu ? (
        <ChartContextMenu
          at={{ left: menu.left, top: menu.top }}
          items={items}
          note={judgedNote(menu.streaming)}
          signedIn={signedIn}
          signInHref={signInHref}
          onClose={closeMenu}
        />
      ) : null}
    </div>
  );
}
