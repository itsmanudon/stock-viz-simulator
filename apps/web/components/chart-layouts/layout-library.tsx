"use client";

/**
 * A6.8: the saved layouts (open, delete) and templates (delete) beside the
 * chart workspace, with their empty and error states. Templates are made on
 * the stock page ("Save as template").
 */

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { deleteLayoutAction, deleteTemplateAction } from "@/app/(product)/(authed)/charts/actions";
import { Button } from "@/components/ui/button";
import type { ChartLayout, ChartTemplate } from "@/lib/api/chart-layouts";
import { CHART_GRIDS } from "@/lib/chart-layouts";
import { chartTypeLabel } from "@/lib/chart-view";
import { indicatorLabel } from "@/lib/stock-workspace";
import { cn } from "@/lib/utils";

export function LayoutLibrary({
  layouts,
  templates,
  currentId,
}: {
  layouts: ChartLayout[] | null;
  templates: ChartTemplate[] | null;
  currentId: number | null;
}) {
  const router = useRouter();
  const [busy, startBusy] = useTransition();
  const [error, setError] = useState<string | null>(null);

  const remove = (work: () => Promise<{ error?: string }>, after?: () => void) => {
    setError(null);
    startBusy(async () => {
      const result = await work();
      if (result.error) setError(result.error);
      else if (after) after();
      else router.refresh();
    });
  };

  return (
    <aside className="min-w-0 space-y-4" aria-label="Saved layouts and templates">
      <section
        aria-labelledby="saved-layouts-title"
        className="rounded-md border border-border-muted bg-card p-3"
        data-testid="saved-layouts"
      >
        <h2 id="saved-layouts-title" className="text-sm font-semibold tracking-tight">
          Saved layouts
        </h2>
        {layouts === null ? (
          <p role="alert" className="mt-2 text-xs text-text-secondary" data-testid="layouts-error">
            Your saved layouts could not load. Reload the page to try again.
          </p>
        ) : layouts.length === 0 ? (
          <p className="mt-2 text-xs leading-5 text-text-tertiary" data-testid="layouts-empty">
            No saved layouts yet. Arrange the charts, name the layout and save it to open it again
            later.
          </p>
        ) : (
          <ul className="mt-2 space-y-1">
            {layouts.map((layout) => (
              <li key={layout.id} className="flex items-center gap-2">
                <Link
                  href={`/charts?layout=${layout.id}`}
                  aria-current={layout.id === currentId ? "page" : undefined}
                  className={cn(
                    "min-w-0 flex-1 truncate rounded-sm px-1.5 py-1 text-xs hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/60",
                    layout.id === currentId
                      ? "font-semibold text-foreground"
                      : "text-text-secondary",
                  )}
                >
                  {layout.name}
                  <span className="ml-1 text-text-tertiary">
                    · {CHART_GRIDS.find((g) => g.value === layout.grid)?.label}
                  </span>
                </Link>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  aria-label={`Delete layout ${layout.name}`}
                  onClick={() =>
                    remove(
                      () => deleteLayoutAction(layout.id),
                      layout.id === currentId ? () => router.push("/charts") : undefined,
                    )
                  }
                >
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section
        aria-labelledby="chart-templates-title"
        className="rounded-md border border-border-muted bg-card p-3"
        data-testid="chart-templates"
      >
        <h2 id="chart-templates-title" className="text-sm font-semibold tracking-tight">
          Templates
        </h2>
        {templates === null ? (
          <p role="alert" className="mt-2 text-xs text-text-secondary">
            Your templates could not load. Reload the page to try again.
          </p>
        ) : templates.length === 0 ? (
          <p className="mt-2 text-xs leading-5 text-text-tertiary" data-testid="templates-empty">
            No templates yet. On a stock page, set up the chart and choose "Save as template".
          </p>
        ) : (
          <ul className="mt-2 space-y-2">
            {templates.map((template) => (
              <li key={template.id} className="flex items-start gap-2">
                <div className="min-w-0 flex-1 text-xs">
                  <p className="truncate font-medium text-foreground">{template.name}</p>
                  <p className="truncate text-text-tertiary">
                    {[
                      chartTypeLabel(template.chart_type),
                      template.scale === "linear" ? null : template.scale,
                      template.indicators.map(indicatorLabel).join(", ") || "No indicators",
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  aria-label={`Delete template ${template.name}`}
                  onClick={() => remove(() => deleteTemplateAction(template.id))}
                >
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        )}
      </section>
      {error ? (
        <p role="alert" className="text-xs text-negative">
          {error}
        </p>
      ) : null}
    </aside>
  );
}
