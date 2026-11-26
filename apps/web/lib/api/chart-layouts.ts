import "server-only";

/**
 * A6.8 (M2.10): chart templates (`/v1/chart-templates`) and layouts
 * (`/v1/chart-layouts`), both authed and per user. The workspace page reads
 * them; `app/(product)/(authed)/charts/actions.ts` writes them.
 */

import type { components } from "./schema";
import { authedDelete, authedGet, authedPatch, authedPost } from "./server";

export type ChartTemplate = components["schemas"]["ChartTemplateOut"];
export type ChartTemplateInput = components["schemas"]["ChartTemplateIn"];
export type ChartLayout = components["schemas"]["ChartLayoutOut"];
export type ChartLayoutInput = components["schemas"]["ChartLayoutIn"];
export type ChartLayoutPatch = components["schemas"]["ChartLayoutPatch"];

export function listChartTemplates(): Promise<ChartTemplate[]> {
  return authedGet("/v1/chart-templates");
}

export function createChartTemplate(body: ChartTemplateInput): Promise<ChartTemplate> {
  return authedPost("/v1/chart-templates", body);
}

export function deleteChartTemplate(id: number): Promise<void> {
  return authedDelete(`/v1/chart-templates/${id}`);
}

export function listChartLayouts(): Promise<ChartLayout[]> {
  return authedGet("/v1/chart-layouts");
}

export function getChartLayout(id: number): Promise<ChartLayout> {
  return authedGet(`/v1/chart-layouts/${id}`);
}

export function createChartLayout(body: ChartLayoutInput): Promise<ChartLayout> {
  return authedPost("/v1/chart-layouts", body);
}

export function updateChartLayout(id: number, body: ChartLayoutPatch): Promise<ChartLayout> {
  return authedPatch(`/v1/chart-layouts/${id}`, body);
}

export function deleteChartLayout(id: number): Promise<void> {
  return authedDelete(`/v1/chart-layouts/${id}`);
}
