"use client";

/**
 * The stock page's chart with drawings (A3.2, M2.4): the drawing toolbar
 * beside `PriceChart`, the drawings on its price pane and the "Drawings"
 * list under it.
 *
 * - Place: pick a tool, then one click (or tap) per anchor; Escape cancels.
 * - Select: click a drawing (or its list item); drag the selected one's
 *   handles or body to move it; Delete or Backspace removes it.
 * - Undo and redo for the session: Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z.
 * - Every change saves through the server actions in
 *   `app/(product)/stocks/[ticker]/drawing-actions.ts`; signed out, the
 *   tools are disabled with "Sign in to save drawings".
 *
 * Anchors are bar dates and prices, so the same drawings render on daily,
 * weekly and monthly bars (`lib/drawings/anchor.ts`).
 *
 * A3.3: an anchored VWAP is a drawing too (one date, a label, bands 0-2).
 * Its line comes from the API (`avwap-actions.ts`), computed from daily bars
 * and sampled at this interval's bars, and is fetched again when the interval,
 * the anchor or the bands change. Quick anchors place one at the loaded bars'
 * highest high, lowest low, or the last earnings date.
 */

import Link from "next/link";
import {
  type ComponentProps,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";

import { avwapAction, lastEarningsDateAction } from "@/app/(product)/stocks/[ticker]/avwap-actions";

import {
  createDrawingAction,
  deleteDrawingAction,
  updateDrawingAction,
} from "@/app/(product)/stocks/[ticker]/drawing-actions";
import { type ChartDrawingLayer, PriceChart } from "@/components/price-chart";
import { barDate } from "@/lib/drawings/anchor";
import {
  EMPTY_HISTORY,
  type History,
  type HistoryEntry,
  inverse,
  record,
  remapId,
  takeRedo,
  takeUndo,
} from "@/lib/drawings/history";
import {
  DEFAULT_STYLE,
  type Drawing,
  type DrawingKind,
  type DrawingPoint,
  type DrawingsResponse,
  defaultAvwapLabel,
  kindSpec,
  toPoints,
} from "@/lib/drawings/kinds";
import type { AvwapLine, SceneDrawing } from "@/lib/drawings/scene";

import { DrawingToolbar } from "./drawing-toolbar";
import { DrawingsList, type PointsDraft } from "./drawings-list";

type ChartProps = Omit<ComponentProps<typeof PriceChart>, "drawingLayer">;

type DrawingResult = { drawing?: Drawing; ok?: boolean; error?: string };
type DrawingCreate = {
  kind: DrawingKind;
  points: ReturnType<typeof toPoints>;
  style: Drawing["style"];
  label: string | null;
  locked: boolean;
};
type DrawingChanges = Partial<Pick<Drawing, "style" | "label" | "locked">> & {
  points?: ReturnType<typeof toPoints>;
};

/**
 * Where drawings are saved. Default: the live chart's `/v1/drawings`
 * (`drawing-actions.ts`). A4.6: a replay session passes its own, so its
 * drawings live and stay in the session.
 */
export type DrawingActions = {
  create: (input: DrawingCreate) => Promise<DrawingResult>;
  update: (id: number, changes: DrawingChanges) => Promise<DrawingResult>;
  remove: (id: number) => Promise<DrawingResult>;
};

type Props = ChartProps & {
  ticker: string;
  signedIn: boolean;
  /** The user's drawings, or null signed out or when they could not be loaded. */
  initial: DrawingsResponse | null;
  callbackUrl: string;
  actions?: DrawingActions;
  /** The tools offered (default every kind). Replay leaves out the anchored VWAP. */
  kinds?: readonly DrawingKind[];
};

function toScene(d: Drawing, avwap?: AvwapLine | null): SceneDrawing {
  return {
    id: String(d.id),
    kind: d.kind,
    points: toPoints(d.points),
    style: d.style,
    label: d.label,
    locked: d.locked,
    ...(d.kind === "avwap" ? { avwap: avwap ?? null } : {}),
  };
}

/** The key an anchored VWAP's line is cached under: what changes it. */
export function avwapKey(d: Pick<Drawing, "id" | "points" | "style">, interval: string): string {
  return `${d.id}:${d.points[0]?.ts ?? ""}:${interval}:${d.style.bands ?? 0}`;
}

/** Quick anchors (A3.3): the loaded bars' highest high and lowest low dates. */
export function extremeDates(
  bars: readonly { ts: string; high: string | number; low: string | number }[],
): { high: string | null; low: string | null } {
  let hi: { v: number; d: string } | null = null;
  let lo: { v: number; d: string } | null = null;
  for (const b of bars) {
    const h = Number(b.high);
    const l = Number(b.low);
    if (Number.isFinite(h) && (!hi || h > hi.v)) hi = { v: h, d: barDate(b.ts) };
    if (Number.isFinite(l) && (!lo || l < lo.v)) lo = { v: l, d: barDate(b.ts) };
  }
  return { high: hi?.d ?? null, low: lo?.d ?? null };
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
    target.closest("form") !== null
  );
}

export function ChartWorkbench({
  ticker,
  signedIn,
  initial,
  callbackUrl,
  actions: given,
  kinds,
  ...chart
}: Props) {
  const actions = useMemo<DrawingActions>(
    () =>
      given ?? {
        create: (input) => createDrawingAction({ ticker, ...input }),
        update: (id, changes) => updateDrawingAction(id, changes),
        remove: (id) => deleteDrawingAction(id),
      },
    [given, ticker],
  );
  const [drawings, setDrawings] = useState<Drawing[]>(initial?.drawings ?? []);
  const [history, setHistory] = useState<History>(EMPTY_HISTORY);
  const [tool, setTool] = useState<DrawingKind | null>(null);
  const [placed, setPlaced] = useState<DrawingPoint[]>([]);
  const [preview, setPreview] = useState<DrawingPoint | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [noteText, setNoteText] = useState("");
  const [avwapBands, setAvwapBands] = useState(1);
  const [avwapLines, setAvwapLines] = useState<Record<string, AvwapLine | null>>({});
  const interval = chart.interval ?? "1d";
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const enabled = signedIn && initial !== null;
  const limit = initial?.limit ?? 200;
  const bounds = { first: initial?.first_bar ?? null, last: initial?.last_bar ?? null };

  const selected = drawings.find((d) => d.id === selectedId) ?? null;

  // Each anchored VWAP's line for this interval, fetched once per anchor,
  // interval and bands (the line follows the data, not the drawing's style).
  useEffect(() => {
    for (const d of drawings) {
      if (d.kind !== "avwap") continue;
      const anchor = d.points[0]?.ts;
      const key = avwapKey(d, interval);
      if (!anchor || key in avwapLines) continue;
      setAvwapLines((lines) => ({ ...lines, [key]: null }));
      void avwapAction(ticker, anchor, interval, d.style.bands ?? 0).then((result) => {
        const line: AvwapLine | null = result.avwap
          ? result.avwap.points.map((p) => ({ ...p, date: barDate(p.ts) }))
          : null;
        if (!result.avwap) setMessage(result.error ?? "The anchored VWAP could not be loaded.");
        setAvwapLines((lines) => ({ ...lines, [key]: line }));
      });
    }
  }, [drawings, interval, ticker, avwapLines]);

  const chooseTool = useCallback((kind: DrawingKind | null) => {
    setTool(kind);
    setPlaced([]);
    setPreview(null);
    setMessage(null);
    if (kind) setSelectedId(null);
  }, []);

  /** Apply one change on the server; returns the drawing it left, if any. */
  const apply = useCallback(
    async (entry: HistoryEntry): Promise<{ ok: boolean; created?: Drawing }> => {
      if (entry.type === "create") {
        const d = entry.drawing;
        const result = await actions.create({
          kind: d.kind,
          points: toPoints(d.points),
          style: d.style,
          label: d.label,
          locked: d.locked,
        });
        if (!result.drawing) {
          setMessage(result.error ?? "The drawing could not be saved.");
          return { ok: false };
        }
        const created = result.drawing;
        setDrawings((list) => [...list, created]);
        return { ok: true, created };
      }
      if (entry.type === "delete") {
        const result = await actions.remove(entry.drawing.id);
        if (result.error) {
          setMessage(result.error);
          return { ok: false };
        }
        setDrawings((list) => list.filter((d) => d.id !== entry.drawing.id));
        setSelectedId((id) => (id === entry.drawing.id ? null : id));
        return { ok: true };
      }
      const target = entry.after;
      const result = await actions.update(target.id, {
        points: toPoints(target.points),
        style: target.style,
        label: target.label,
        locked: target.locked,
      });
      if (!result.drawing) {
        setMessage(result.error ?? "The drawing could not be saved.");
        return { ok: false };
      }
      const saved = result.drawing;
      setDrawings((list) => list.map((d) => (d.id === saved.id ? saved : d)));
      return { ok: true };
    },
    [actions],
  );

  const run = useCallback(async (work: () => Promise<void>) => {
    setBusy(true);
    try {
      await work();
    } finally {
      setBusy(false);
    }
  }, []);

  const create = useCallback(
    (input: Omit<Drawing, "id" | "ticker" | "created_at" | "updated_at" | "position">) =>
      run(async () => {
        const result = await actions.create({
          ...input,
          points: toPoints(input.points),
        });
        if (!result.drawing) {
          setMessage(result.error ?? "The drawing could not be saved.");
          return;
        }
        const created = result.drawing;
        setDrawings((list) => [...list, created]);
        setHistory((h) => record(h, { type: "create", drawing: created }));
        setSelectedId(created.id);
        setMessage(`${kindSpec(created.kind).label} saved.`);
      }),
    [run, actions],
  );

  const update = useCallback(
    (before: Drawing, changes: Partial<Pick<Drawing, "points" | "style" | "label" | "locked">>) =>
      run(async () => {
        const after = { ...before, ...changes };
        const result = await apply({ type: "update", before, after });
        if (result.ok) {
          setHistory((h) => record(h, { type: "update", before, after }));
          setMessage(null);
        }
      }),
    [apply, run],
  );

  const remove = useCallback(
    (drawing: Drawing) =>
      run(async () => {
        if (drawing.locked) {
          setMessage("Unlock the drawing before deleting it.");
          return;
        }
        const result = await apply({ type: "delete", drawing });
        if (result.ok) {
          setHistory((h) => record(h, { type: "delete", drawing }));
          setMessage(`${kindSpec(drawing.kind).label} deleted.`);
        }
      }),
    [apply, run],
  );

  const step = useCallback(
    (direction: "undo" | "redo") =>
      run(async () => {
        const taken = direction === "undo" ? takeUndo(history) : takeRedo(history);
        if (!taken) return;
        const change = direction === "undo" ? inverse(taken.entry) : taken.entry;
        const result = await apply(change);
        if (!result.ok) return;
        let next = taken.next;
        if (change.type === "create" && result.created) {
          next = remapId(next, change.drawing.id, result.created.id);
        }
        setHistory(next);
        setMessage(direction === "undo" ? "Undone." : "Redone.");
      }),
    [apply, history, run],
  );

  const onPlace = useCallback(
    (point: DrawingPoint) => {
      if (!tool) return;
      const spec = kindSpec(tool);
      const points = [...placed, point];
      if (points.length < spec.points) {
        setPlaced(points);
        return;
      }
      setPlaced([]);
      setPreview(null);
      const kind = tool;
      setTool(null);
      void create({
        kind,
        points,
        style: kind === "avwap" ? { ...DEFAULT_STYLE, bands: avwapBands } : DEFAULT_STYLE,
        label:
          kind === "text"
            ? noteText.trim() || "Note"
            : kind === "avwap"
              ? noteText.trim() || defaultAvwapLabel(points[0]?.ts ?? null)
              : null,
        locked: false,
      });
    },
    [tool, placed, create, noteText, avwapBands],
  );

  const anchorAvwap = useCallback(
    (date: string | null, why: string) => {
      if (!date) {
        setMessage(`No ${why} to anchor to.`);
        return;
      }
      void create({
        kind: "avwap",
        points: [{ ts: date, price: "" }],
        style: { ...DEFAULT_STYLE, bands: avwapBands },
        label: noteText.trim() || defaultAvwapLabel(date),
        locked: false,
      });
    },
    [create, avwapBands, noteText],
  );

  const extremes = useMemo(() => extremeDates(chart.bars), [chart.bars]);

  const sceneDrawings = useMemo(() => {
    const saved = drawings.map((d) =>
      toScene(d, d.kind === "avwap" ? avwapLines[avwapKey(d, interval)] : undefined),
    );
    if (!tool) return saved;
    const spec = kindSpec(tool);
    const points = [...placed, ...(preview ? [preview] : [])].slice(0, spec.points);
    if (points.length === 0) return saved;
    return [
      ...saved,
      {
        id: "draft",
        kind: tool,
        points,
        style: DEFAULT_STYLE,
        label: tool === "text" ? noteText || "Note" : tool === "avwap" ? noteText || null : null,
      },
    ];
  }, [drawings, tool, placed, preview, noteText, avwapLines, interval]);

  const layer: ChartDrawingLayer | undefined = enabled
    ? {
        drawings: sceneDrawings,
        selectedId: selectedId === null ? null : String(selectedId),
        placingKind: tool,
        placedCount: placed.length,
        onPlace,
        onPreview: setPreview,
        onSelect: (id) => setSelectedId(id === null ? null : Number(id)),
        onMoved: (id, points) => {
          const before = drawings.find((d) => String(d.id) === id);
          if (before) void update(before, { points });
        },
      }
    : undefined;

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!enabled || isTyping(event.target)) return;
    const mod = event.metaKey || event.ctrlKey;
    if (event.key === "Escape") {
      if (tool) chooseTool(null);
      else setSelectedId(null);
    } else if ((event.key === "Delete" || event.key === "Backspace") && selected) {
      event.preventDefault();
      void remove(selected);
    } else if (mod && event.key.toLowerCase() === "z") {
      event.preventDefault();
      void step(event.shiftKey ? "redo" : "undo");
    } else if (mod && event.key.toLowerCase() === "y") {
      event.preventDefault();
      void step("redo");
    }
  };

  const prompt = tool
    ? `${kindSpec(tool).label}: click ${kindSpec(tool).steps[placed.length]} (${placed.length + 1} of ${kindSpec(tool).points}). Escape cancels.`
    : selected
      ? `Selected: ${kindSpec(selected.kind).label}${selected.locked ? " (locked)" : ". Drag it or its handles to move; Delete removes it."}`
      : null;

  return (
    <div className="space-y-2" onKeyDown={onKeyDown} data-testid="chart-workbench">
      <div className="flex flex-col gap-2 sm:flex-row">
        <DrawingToolbar
          tool={tool}
          onTool={chooseTool}
          enabled={enabled}
          canUndo={history.past.length > 0}
          canRedo={history.future.length > 0}
          onUndo={() => void step("undo")}
          onRedo={() => void step("redo")}
          selectedLocked={selected ? selected.locked : null}
          onToggleLock={() => selected && void update(selected, { locked: !selected.locked })}
          onDelete={() => selected && void remove(selected)}
          busy={busy}
          kinds={kinds}
        />
        <div className="min-w-0 flex-1">
          <PriceChart {...chart} drawingLayer={layer} />
        </div>
      </div>
      <div className="flex min-h-5 flex-wrap items-center gap-2 px-1 text-2xs text-text-tertiary">
        {!signedIn ? (
          <p data-testid="drawings-signed-out">
            <Link
              href={`/login?callbackUrl=${encodeURIComponent(callbackUrl)}`}
              className="text-text-secondary underline underline-offset-2 hover:text-foreground"
            >
              Sign in to save drawings
            </Link>
          </p>
        ) : initial === null ? (
          <p>Your drawings could not be loaded, so the tools are off. Reload to try again.</p>
        ) : null}
        {tool === "avwap" ? (
          <>
            <label className="flex items-center gap-1">
              AVWAP label
              <input
                type="text"
                maxLength={80}
                value={noteText}
                placeholder="e.g. swing"
                onChange={(event) => setNoteText(event.target.value)}
                className="h-6 rounded-sm border border-border-muted bg-background px-1.5 text-2xs text-foreground"
                data-testid="avwap-label"
              />
            </label>
            <label className="flex items-center gap-1">
              Bands
              <select
                value={avwapBands}
                onChange={(event) => setAvwapBands(Number(event.target.value))}
                className="h-6 rounded-sm border border-border-muted bg-background px-1 text-2xs text-foreground"
                data-testid="avwap-bands"
              >
                <option value={0}>None</option>
                <option value={1}>±1σ</option>
                <option value={2}>±1σ and ±2σ</option>
              </select>
            </label>
            <span className="flex flex-wrap items-center gap-1" data-testid="avwap-quick">
              Or anchor at:
              <button
                type="button"
                className="rounded-sm border border-border-muted px-1.5 py-0.5 hover:text-foreground disabled:opacity-40"
                disabled={busy}
                onClick={() => {
                  chooseTool(null);
                  anchorAvwap(extremes.high, "highest high");
                }}
              >
                Highest high in view
              </button>
              <button
                type="button"
                className="rounded-sm border border-border-muted px-1.5 py-0.5 hover:text-foreground disabled:opacity-40"
                disabled={busy}
                onClick={() => {
                  chooseTool(null);
                  anchorAvwap(extremes.low, "lowest low");
                }}
              >
                Lowest low in view
              </button>
              <button
                type="button"
                className="rounded-sm border border-border-muted px-1.5 py-0.5 hover:text-foreground disabled:opacity-40"
                disabled={busy || !bounds.first || !bounds.last}
                onClick={() => {
                  chooseTool(null);
                  if (!bounds.first || !bounds.last) return;
                  void lastEarningsDateAction(ticker, bounds.first, bounds.last).then((r) =>
                    r.error ? setMessage(r.error) : anchorAvwap(r.date, "earnings date"),
                  );
                }}
              >
                Last earnings date
              </button>
            </span>
          </>
        ) : null}
        {tool === "text" ? (
          <label className="flex items-center gap-1">
            Note text
            <input
              type="text"
              maxLength={80}
              value={noteText}
              onChange={(event) => setNoteText(event.target.value)}
              className="h-6 rounded-sm border border-border-muted bg-background px-1.5 text-2xs text-foreground"
            />
          </label>
        ) : null}
        <p aria-live="polite" data-testid="drawing-status">
          {message ?? prompt ?? ""}
        </p>
      </div>
      {enabled || drawings.length ? (
        <DrawingsList
          drawings={drawings}
          selectedId={selectedId}
          onSelect={setSelectedId}
          kinds={kinds}
          enabled={enabled}
          busy={busy}
          bounds={bounds}
          limit={limit}
          onAdd={(draft: PointsDraft) =>
            void create({
              kind: draft.kind,
              points: draft.points,
              style: { ...DEFAULT_STYLE, colour: draft.colour, bands: draft.bands ?? 0 },
              label: draft.label.trim() || null,
              locked: false,
            })
          }
          onEdit={(drawing, draft) =>
            void update(drawing, {
              points: draft.points,
              label: draft.label.trim() || null,
              style: { ...drawing.style, colour: draft.colour, bands: draft.bands ?? 0 },
            })
          }
          onToggleLock={(drawing) => void update(drawing, { locked: !drawing.locked })}
          onDelete={(drawing) => void remove(drawing)}
        />
      ) : null}
    </div>
  );
}
