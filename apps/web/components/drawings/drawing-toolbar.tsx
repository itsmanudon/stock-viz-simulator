"use client";

/**
 * The drawing toolbar beside the chart (A3.2): one button per tool, each
 * with a spoken name and `aria-pressed`, then undo, redo, lock and delete for
 * the selected drawing. Signed out, every control is disabled and the bar
 * says "Sign in to save drawings".
 */

import {
  AlignJustify,
  ChartNoAxesGantt,
  Equal,
  Lock,
  LockOpen,
  type LucideIcon,
  Minus,
  MousePointer2,
  MoveUpRight,
  Percent,
  Redo2,
  Ruler,
  Slash,
  Square,
  Trash2,
  TrendingDown,
  TrendingUp,
  Type,
  Undo2,
} from "lucide-react";

import { type DrawingKind, KIND_SPECS } from "@/lib/drawings/kinds";
import { cn } from "@/lib/utils";

const ICONS: Record<DrawingKind, LucideIcon> = {
  trendline: Slash,
  ray: MoveUpRight,
  hline: Minus,
  rectangle: Square,
  channel: Equal,
  fib_retracement: AlignJustify,
  fib_extension: Percent,
  ruler: Ruler,
  text: Type,
  position_long: TrendingUp,
  position_short: TrendingDown,
};

type Props = {
  tool: DrawingKind | null;
  onTool: (kind: DrawingKind | null) => void;
  enabled: boolean;
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
  selectedLocked: boolean | null;
  onToggleLock: () => void;
  onDelete: () => void;
  busy: boolean;
};

function ToolButton({
  label,
  icon: Icon,
  pressed,
  disabled,
  onClick,
  testId,
  shortcut,
}: {
  label: string;
  icon: LucideIcon;
  pressed?: boolean;
  disabled?: boolean;
  onClick: () => void;
  testId?: string;
  shortcut?: string;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={pressed}
      aria-keyshortcuts={shortcut}
      title={label}
      disabled={disabled}
      onClick={onClick}
      data-testid={testId}
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-sm text-text-secondary transition-colors",
        "hover:bg-surface-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60",
        "disabled:pointer-events-none disabled:opacity-40",
        pressed && "bg-brand/15 text-brand hover:bg-brand/20 hover:text-brand",
      )}
    >
      <Icon className="size-4" aria-hidden />
    </button>
  );
}

export function DrawingToolbar({
  tool,
  onTool,
  enabled,
  canUndo,
  canRedo,
  onUndo,
  onRedo,
  selectedLocked,
  onToggleLock,
  onDelete,
  busy,
}: Props) {
  return (
    <div
      role="toolbar"
      aria-label="Drawing tools"
      className="flex shrink-0 items-center gap-0.5 overflow-x-auto border-border-muted border-b pb-1 sm:grid sm:grid-cols-2 sm:content-start sm:self-start sm:overflow-visible sm:border-r sm:border-b-0 sm:pr-1 sm:pb-0"
      data-testid="drawing-toolbar"
    >
      <ToolButton
        label="Select and move"
        icon={MousePointer2}
        pressed={tool === null}
        disabled={!enabled}
        onClick={() => onTool(null)}
      />
      {KIND_SPECS.map((spec) => (
        <ToolButton
          key={spec.kind}
          label={spec.label}
          icon={ICONS[spec.kind] ?? ChartNoAxesGantt}
          pressed={tool === spec.kind}
          disabled={!enabled}
          onClick={() => onTool(tool === spec.kind ? null : spec.kind)}
          testId={`drawing-tool-${spec.kind}`}
        />
      ))}
      <span
        aria-hidden
        className="mx-1 h-5 w-px shrink-0 bg-border-muted sm:col-span-2 sm:mx-0 sm:my-1 sm:h-px sm:w-full"
      />
      <ToolButton
        label="Undo"
        icon={Undo2}
        disabled={!enabled || !canUndo || busy}
        onClick={onUndo}
        shortcut="Control+Z Meta+Z"
      />
      <ToolButton
        label="Redo"
        icon={Redo2}
        disabled={!enabled || !canRedo || busy}
        onClick={onRedo}
        shortcut="Control+Shift+Z Meta+Shift+Z"
      />
      <ToolButton
        label={selectedLocked ? "Unlock the selected drawing" : "Lock the selected drawing"}
        icon={selectedLocked ? LockOpen : Lock}
        pressed={selectedLocked ?? undefined}
        disabled={!enabled || selectedLocked === null || busy}
        onClick={onToggleLock}
      />
      <ToolButton
        label="Delete the selected drawing"
        icon={Trash2}
        disabled={!enabled || selectedLocked === null || selectedLocked || busy}
        onClick={onDelete}
        shortcut="Delete Backspace"
      />
    </div>
  );
}
