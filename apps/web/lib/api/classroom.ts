import "server-only";

/** A10.2 (M12.1, M12.2): cohorts, assignments and the gradebook, as the signed-in user. */

import type { components } from "./schema";
import { authedDelete, authedGet, authedPost } from "./server";

export type Cohort = components["schemas"]["CohortOut"];
export type CohortAssignment = components["schemas"]["CohortAssignmentOut"];
export type Gradebook = components["schemas"]["GradebookOut"];
export type CohortStart = components["schemas"]["CohortStartOut"];
export type AssignmentIn = components["schemas"]["CohortAssignmentIn"];

export function listCohorts(): Promise<Cohort[]> {
  return authedGet<Cohort[]>("/v1/cohorts");
}

export function createCohort(name: string): Promise<Cohort> {
  return authedPost<Cohort>("/v1/cohorts", { name });
}

export function joinCohort(code: string, consent: boolean): Promise<Cohort> {
  return authedPost<Cohort>("/v1/cohorts/join", { code, consent });
}

export function leaveCohort(id: number): Promise<void> {
  return authedDelete(`/v1/cohorts/${id}/membership`);
}

export function addAssignment(cohortId: number, body: AssignmentIn): Promise<CohortAssignment> {
  return authedPost<CohortAssignment>(`/v1/cohorts/${cohortId}/assignments`, body);
}

export function startAssignment(id: number): Promise<CohortStart> {
  return authedPost<CohortStart>(`/v1/assignments/${id}/start`);
}

export function getGradebook(cohortId: number): Promise<Gradebook> {
  return authedGet<Gradebook>(`/v1/cohorts/${cohortId}/gradebook`);
}
