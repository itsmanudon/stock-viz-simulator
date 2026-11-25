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
 */

import Link from "next/link";
import { type ComponentProps, type KeyboardEvent, useCallback, useMemo, useState } from "react";

import {
  createDrawingAction,
  deleteDrawingAction,
  updateDrawingAction,
} from "@/app/(product)/stocks/[ticker]/drawing-actions";
import { type ChartDrawingLayer, PriceChart } from "@/components/price-chart";
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
  kindSpec,
  toPoints,
} from "@/lib/drawings/kinds";
import type { SceneDrawing } from "@/lib/drawings/scene";

import { DrawingToolbar } from "./drawing-toolbar";
import { DrawingsList, type PointsDraft } from "./drawings-list";

type ChartProps = Omit<ComponentProps<typeof PriceChart>, "drawingLayer">;

type Props = ChartProps & {
  ticker: string;
  signedIn: boolean;
  /** The user's drawings, or null signed out or when they could not be loaded. */
  initial: DrawingsResponse | null;
  callbackUrl: string;
};

function toScene(d: Drawing): SceneDrawing {
  return {
    id: String(d.id),
    kind: d.kind,
    points: toPoints(d.points),
    style: d.style,
    label: d.label,
    locked: d.locked,
  };
}

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName) ||
    target.closest("form") !== null
  );
}

export function ChartWorkbench({ ticker, signedIn, initial, callbackUrl, ...chart }: Props) {
  const [drawings, setDrawings] = useState<Drawing[]>(initial?.drawings ?? []);
  const [history, setHistory] = useState<History>(EMPTY_HISTORY);
  const [tool, setTool] = useState<DrawingKind | null>(null);
  const [placed, setPlaced] = useState<DrawingPoint[]>([]);
  const [preview, setPreview] = useState<DrawingPoint | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [noteText, setNoteText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const enabled = signedIn && initial !== null;
  const limit = initial?.limit ?? 200;
  const bounds = { first: initial?.first_bar ?? null, last: initial?.last_bar ?? null };

  const selected = drawings.find((d) => d.id === selectedId) ?? null;

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
        const result = await createDrawingAction({
          ticker,
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
        const result = await deleteDrawingAction(entry.drawing.id);
        if (result.error) {
          setMessage(result.error);
          return { ok: false };
        }
        setDrawings((list) => list.filter((d) => d.id !== entry.drawing.id));
        setSelectedId((id) => (id === entry.drawing.id ? null : id));
        return { ok: true };
      }
      const target = entry.after;
      const result = await updateDrawingAction(target.id, {
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
    [ticker],
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
        const result = await createDrawingAction({
          ticker,
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
    [run, ticker],
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
        style: DEFAULT_STYLE,
        label: kind === "text" ? noteText.trim() || "Note" : null,
        locked: false,
      });
    },
    [tool, placed, create, noteText],
  );

  const sceneDrawings = useMemo(() => {
    const saved = drawings.map(toScene);
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
        label: tool === "text" ? noteText || "Note" : null,
      },
    ];
  }, [drawings, tool, placed, preview, noteText]);

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
          enabled={enabled}
          busy={busy}
          bounds={bounds}
          limit={limit}
          onAdd={(draft: PointsDraft) =>
            void create({
              kind: draft.kind,
              points: draft.points,
              style: { ...DEFAULT_STYLE, colour: draft.colour },
              label: draft.label.trim() || null,
              locked: false,
            })
          }
          onEdit={(drawing, draft) =>
            void update(drawing, {
              points: draft.points,
              label: draft.label.trim() || null,
              style: { ...drawing.style, colour: draft.colour },
            })
          }
          onToggleLock={(drawing) => void update(drawing, { locked: !drawing.locked })}
          onDelete={(drawing) => void remove(drawing)}
        />
      ) : null}
    </div>
  );
}
