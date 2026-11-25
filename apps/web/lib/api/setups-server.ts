import "server-only";

import { authedGet, authedPost } from "./server";
import type { Setup, SetupDetail, SetupKind } from "./setups";

/** Your setups and the presets (A2.2). */
export function listSetups(includeArchived = false): Promise<Setup[]> {
  return authedGet<Setup[]>(`/v1/setups${includeArchived ? "?include_archived=true" : ""}`);
}

export function getSetup(id: number): Promise<SetupDetail> {
  return authedGet<SetupDetail>(`/v1/setups/${id}`);
}

export function createSetup(input: {
  name: string;
  rule: string;
  kind?: SetupKind;
  description?: string;
  notes?: string;
}): Promise<SetupDetail> {
  return authedPost<SetupDetail>("/v1/setups", { kind: "screen", ...input });
}

export function forkSetup(id: number, name?: string): Promise<SetupDetail> {
  return authedPost<SetupDetail>(`/v1/setups/${id}/fork`, name ? { name } : {});
}

export function archiveSetup(id: number): Promise<SetupDetail> {
  return authedPost<SetupDetail>(`/v1/setups/${id}/archive`);
}
