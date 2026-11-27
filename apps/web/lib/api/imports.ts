import "server-only";

/**
 * A5.3: the Zerodha tradebook import into an imported book
 * (`/v1/books/{id}/imports`, `/opening-lots`). The CSV goes from the server
 * action to the API as a `text/csv` body; the browser never calls the API.
 * Preview stores nothing; commit sends the same bytes with the preview's
 * SHA-256 (the API refuses a different file).
 *
 * A6.11: both take the column map: "auto" (detect from the header row), a
 * built-in map's name, or `saved:<id>` (the user's own map, `/v1/import-maps`).
 */

import { importQueryString } from "../tradebook-import";
import type { components } from "./schema";
import { authedDelete, authedGet, authedPost, authedPostText } from "./server";

export type ImportPreview = components["schemas"]["ImportPreviewOut"];
export type ImportCommit = components["schemas"]["ImportCommitOut"];
export type ImportsStatus = components["schemas"]["ImportsOut"];
export type ImportBatch = components["schemas"]["ImportBatchOut"];
export type ImportProblem = components["schemas"]["ImportProblemOut"];
export type ImportTrade = components["schemas"]["ImportTradeOut"];
export type OpeningLot = components["schemas"]["OpeningLotOut"];
export type OpeningLotInput = components["schemas"]["OpeningLotIn"];
export type ImportMap = components["schemas"]["ImportMapOut"];
export type SavedImportMap = components["schemas"]["SavedImportMapOut"];
export type SavedImportMapInput = components["schemas"]["SavedImportMapIn"];

export function getImports(bookId: number): Promise<ImportsStatus> {
  return authedGet<ImportsStatus>(`/v1/books/${bookId}/imports`);
}

export function previewImport(
  bookId: number,
  csv: ArrayBuffer,
  map = "auto",
): Promise<ImportPreview> {
  const query = importQueryString(map).replace(/^&/, "?");
  return authedPostText<ImportPreview>(
    `/v1/books/${bookId}/imports/preview${query}`,
    csv,
    "text/csv",
  );
}

export function commitImport(
  bookId: number,
  csv: ArrayBuffer,
  sha256: string,
  map = "auto",
): Promise<ImportCommit> {
  return authedPostText<ImportCommit>(
    `/v1/books/${bookId}/imports/commit?file_sha256=${encodeURIComponent(sha256)}${importQueryString(map)}`,
    csv,
    "text/csv",
  );
}

export function saveImportMap(body: SavedImportMapInput): Promise<SavedImportMap> {
  return authedPost<SavedImportMap>("/v1/import-maps", body);
}

export function deleteImportMap(mapId: number): Promise<void> {
  return authedDelete(`/v1/import-maps/${mapId}`);
}

export function deleteImport(bookId: number, batchId: number): Promise<void> {
  return authedDelete(`/v1/books/${bookId}/imports/${batchId}`);
}

export function addOpeningLot(bookId: number, body: OpeningLotInput): Promise<OpeningLot> {
  return authedPost<OpeningLot>(`/v1/books/${bookId}/opening-lots`, body);
}

export function deleteOpeningLot(bookId: number, lotId: number): Promise<void> {
  return authedDelete(`/v1/books/${bookId}/opening-lots/${lotId}`);
}
