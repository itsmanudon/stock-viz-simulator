"use client";

/**
 * A5.3, A6.11: "Import tradebook (CSV)" for an imported book. Choose the file
 * and its column map (detected from the header row, a broker's map, or your
 * own), see the preview (which map was used and which columns matched, the
 * first trades, every problem by row), then Confirm import. The file stays in
 * this component between the two steps and is sent again at commit with the
 * preview's SHA-256 and the same map; the API stores nothing at preview.
 * "Map Columns Yourself" picks the file's header for each field and saves it
 * as one of your maps (header names only). Batch history (with a two-step
 * delete), the opening-lot form and the sells still waiting for one sit below.
 *
 * Keyboard: every control is a native input, select, button or link; the
 * preview's result is announced (`aria-live`). Phone: tables scroll sideways
 * inside their card, the forms stack.
 */

import { FileUp, Info, Trash2 } from "lucide-react";
import { useActionState, useId, useRef, useState, useTransition } from "react";

import {
  type CommitState,
  type ImportActionState,
  type PreviewState,
  addOpeningLotAction,
  commitTradebookAction,
  deleteImportAction,
  deleteImportMapAction,
  deleteOpeningLotAction,
  previewTradebookAction,
  saveImportMapAction,
} from "@/app/(product)/(authed)/portfolio/import/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ImportBatch, ImportPreview, ImportsStatus, SavedImportMap } from "@/lib/api/imports";
import { formatCurrency } from "@/lib/portfolio-view-model";
import {
  MAP_FIELDS,
  PROBLEM_LABELS,
  PRODUCT_LABELS,
  type ProblemKind,
  checkTradebookFile,
  countItems,
  guessMapping,
  headerRowFromText,
  mappingProblem,
  marketZone,
  problemSkipsRow,
} from "@/lib/tradebook-import";

const CARD = "rounded-lg border border-border-muted bg-surface-secondary/30";
const SELECT =
  "h-9 w-full rounded-md border border-input bg-transparent px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const INITIAL: ImportActionState = {};

type Market = "in" | "us";

function dateTime(iso: string, timeKnown = true, market: Market = "in"): string {
  const zone = marketZone(market);
  const d = new Date(/(Z|[+-]\d{2}:\d{2})$/.test(iso) ? iso : `${iso}Z`);
  const opts: Intl.DateTimeFormatOptions = timeKnown
    ? { dateStyle: "medium", timeStyle: "short", timeZone: zone.timeZone }
    : { dateStyle: "medium", timeZone: zone.timeZone };
  return (
    d.toLocaleString(market === "us" ? "en-US" : "en-IN", opts) +
    (timeKnown ? ` ${zone.label}` : "")
  );
}

const STATUS_LABEL: Record<string, string> = {
  unconfirmed: "Unconfirmed",
  confirmed: "Confirmed",
  custom: "Your Map",
};

const DETECTED_LABEL: Record<string, string> = {
  header: "detected from the header row",
  chosen: "chosen by you",
  saved: "your saved map",
  fallback: "no map fits the header row",
};

export function TradebookImport({ bookId, status }: { bookId: number; status: ImportsStatus }) {
  const market: Market = status.market === "us" ? "us" : "in";
  const currency = status.currency ?? (market === "us" ? "USD" : "INR");
  return (
    <div className="space-y-6">
      <FormatNote status={status} market={market} />
      <UploadFlow bookId={bookId} status={status} market={market} currency={currency} />
      <SavedMaps maps={status.saved_maps ?? []} />
      <NeedsOpeningLot status={status} market={market} />
      <OpeningLots bookId={bookId} status={status} market={market} currency={currency} />
      <BatchHistory bookId={bookId} batches={status.batches} market={market} />
      <p className="text-2xs leading-relaxed text-text-tertiary">
        StockViz keeps each trade&apos;s parsed fields and the file&apos;s fingerprint (SHA-256),
        never the file, its name or your client id. A saved map keeps header names only. Deleting an
        import removes its trades for good; database backups still hold deleted rows until they age
        out.
      </p>
    </div>
  );
}

function FormatNote({ status, market }: { status: ImportsStatus; market: Market }) {
  return (
    <p
      role="note"
      className="flex items-start gap-2 rounded-md border border-border-muted bg-surface-secondary/50 px-3 py-2.5 text-xs text-text-secondary"
    >
      <Info className="mt-px size-3.5 shrink-0 text-text-tertiary" aria-hidden />
      {market === "us" ? (
        <span>
          <span className="font-medium text-text-primary">US book.</span> StockViz has no map for a
          US broker&apos;s file: choose the file, then map its columns yourself once and save the
          map. Option rows are counted and skipped, and no charges are estimated.
        </span>
      ) : (
        <span>
          <span className="font-medium text-text-primary">Formats unconfirmed.</span>{" "}
          {status.format_note} The map is detected from the file&apos;s header row; Zerodha, Dhan,
          Fyers, Upstox, Angel One and Groww each have one, and any other file can be mapped
          yourself.
        </span>
      )}
    </p>
  );
}

function UploadFlow({
  bookId,
  status,
  market,
  currency,
}: {
  bookId: number;
  status: ImportsStatus;
  market: Market;
  currency: string;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const saved = status.saved_maps ?? [];
  const brokerMaps = market === "in" ? (status.maps ?? []) : [];
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [choice, setChoice] = useState<string>(
    market === "us" && saved[0] ? `saved:${saved[0].id}` : "auto",
  );
  const [extraMaps, setExtraMaps] = useState<{ id: number; name: string }[]>([]);
  const [mapping, setMapping] = useState(false);
  const [preview, setPreview] = useState<PreviewState>({});
  const [commit, setCommit] = useState<CommitState>({});
  const [busy, start] = useTransition();

  const savedChoices = [
    ...saved.map((m) => ({ id: m.id, name: m.name })),
    ...extraMaps.filter((e) => !saved.some((m) => m.id === e.id)),
  ];

  function choose(next: File | null) {
    setPreview({});
    setCommit({});
    setFile(next);
    setHeaders([]);
    setFileError(next ? checkTradebookFile(next) : null);
    if (next && !checkTradebookFile(next)) {
      void next
        .slice(0, 64 * 1024)
        .text()
        .then((text) => setHeaders(headerRowFromText(text)))
        .catch(() => setHeaders([]));
      if (market === "us" && savedChoices.length === 0) setMapping(true);
    }
  }

  function form(extra?: Record<string, string>): FormData {
    const data = new FormData();
    data.set("book_id", String(bookId));
    if (file) data.set("file", file);
    for (const [k, v] of Object.entries(extra ?? {})) data.set(k, v);
    return data;
  }

  function runPreview(map: string) {
    if (!file || fileError) return;
    setCommit({});
    start(async () => {
      const result = await previewTradebookAction(form({ map }));
      setPreview(result);
      if (result.preview?.missing_required.length) setMapping(true);
    });
  }

  function runCommit() {
    const sha = preview.preview?.file_sha256;
    if (!file || !sha) return;
    start(async () => {
      const result = await commitTradebookAction(form({ file_sha256: sha, map: choice }));
      setCommit(result);
      if (result.result) {
        setPreview({});
        setFile(null);
        setHeaders([]);
        setMapping(false);
        if (input.current) input.current.value = "";
      }
    });
  }

  function onSaved(saved: { id: number; name: string }) {
    const next = `saved:${saved.id}`;
    setExtraMaps((prev) => [...prev.filter((m) => m.id !== saved.id), saved]);
    setChoice(next);
    setMapping(false);
    runPreview(next);
  }

  const p = preview.preview;
  const fileHeaders = p?.headers?.length ? p.headers : headers;
  const needsMap = market === "us" && choice === "auto";
  return (
    <section aria-labelledby={`${id}-title`} className={`${CARD} space-y-4 p-4`}>
      <div>
        <h2 id={`${id}-title`} className="text-sm font-medium text-text-primary">
          Import Tradebook (CSV)
        </h2>
        <p className="mt-1 text-xs leading-relaxed text-text-tertiary">
          {market === "us"
            ? "Download your US broker's trade history as CSV. Files up to 2 MB."
            : "Download your broker's tradebook for the equity segment as CSV (an Excel download: save it as CSV first). Files up to 2 MB. F&O and commodity trades are counted and skipped."}
        </p>
        {market === "in" ? (
          <details className="mt-2 text-xs text-text-tertiary">
            <summary className="cursor-pointer text-text-secondary">
              Where Each Broker Keeps It
            </summary>
            <ul className="mt-1 space-y-1">
              {brokerMaps.map((m) => (
                <li key={m.name}>
                  <span className="text-text-secondary">{m.label}:</span> {m.how_to}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          runPreview(choice);
        }}
        className="grid gap-3 sm:grid-cols-[1fr_minmax(12rem,16rem)_auto] sm:items-end"
      >
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-file`} className="text-xs">
            Tradebook File
          </Label>
          <Input
            ref={input}
            id={`${id}-file`}
            name="file"
            type="file"
            accept=".csv,text/csv"
            aria-describedby={fileError ? `${id}-file-error` : undefined}
            onChange={(e) => choose(e.target.files?.[0] ?? null)}
            className="cursor-pointer file:mr-3 file:text-xs file:font-medium"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-map`} className="text-xs">
            Column Map
          </Label>
          <select
            id={`${id}-map`}
            name="map"
            value={choice}
            onChange={(e) => {
              setChoice(e.target.value);
              setPreview({});
            }}
            className={SELECT}
          >
            <option value="auto">
              {market === "us" ? "Choose Your Map" : "Detect From Header Row"}
            </option>
            {brokerMaps.map((m) => (
              <option key={m.name} value={m.name}>
                {m.label} (Unconfirmed)
              </option>
            ))}
            {savedChoices.map((m) => (
              <option key={m.id} value={`saved:${m.id}`}>
                {m.name} (Your Map)
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" disabled={!file || Boolean(fileError) || busy || needsMap}>
          <FileUp className="size-4" aria-hidden />
          {busy && !p ? "Reading…" : "Preview"}
        </Button>
      </form>
      {fileError ? (
        <p id={`${id}-file-error`} role="alert" className="text-xs text-loss">
          {fileError}
        </p>
      ) : null}
      {file && !fileError ? (
        <div>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            aria-expanded={mapping}
            onClick={() => setMapping((v) => !v)}
          >
            {mapping ? "Hide Column Mapping" : "Map Columns Yourself"}
          </Button>
        </div>
      ) : null}
      {mapping && file && !fileError ? (
        <ColumnMapper headers={fileHeaders} market={market} onSaved={onSaved} />
      ) : null}
      <div aria-live="polite" className="space-y-4">
        {preview.error ? (
          <p role="alert" className="text-xs text-loss">
            {preview.error}
          </p>
        ) : null}
        {commit.error ? (
          <p role="alert" className="text-xs text-loss">
            {commit.error}
          </p>
        ) : null}
        {commit.result ? (
          <p className="rounded-md border border-gain/30 bg-gain/10 px-3 py-2 text-xs text-text-primary">
            {commit.result.added > 0
              ? `Imported ${commit.result.added} trade${commit.result.added === 1 ? "" : "s"}. ${
                  commit.result.counts.needs_opening_lot > 0
                    ? `${commit.result.counts.needs_opening_lot} sell${commit.result.counts.needs_opening_lot === 1 ? " waits" : "s wait"} for an opening lot (below).`
                    : "Positions are rebuilt."
                }`
              : "Nothing new: every trade in the file is already in this book."}
          </p>
        ) : null}
        {p ? (
          <PreviewPanel
            preview={p}
            busy={busy}
            onConfirm={runCommit}
            market={market}
            currency={currency}
          />
        ) : null}
      </div>
    </section>
  );
}

function ColumnMapper({
  headers,
  market,
  onSaved,
}: {
  headers: string[];
  market: Market;
  onSaved: (saved: { id: number; name: string }) => void;
}) {
  const id = useId();
  const [values, setValues] = useState<Record<string, string>>(() => guessMapping(headers));
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();
  const seenHeaders = headers.join("\u0000");
  const [forHeaders, setForHeaders] = useState(seenHeaders);
  if (forHeaders !== seenHeaders) {
    setForHeaders(seenHeaders);
    setValues(guessMapping(headers));
  }

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const problem = mappingProblem(values);
    if (problem) {
      setError(problem);
      return;
    }
    const data = new FormData(event.currentTarget);
    start(async () => {
      const result = await saveImportMapAction(data);
      if (result.error || result.id == null) {
        setError(result.error ?? "The map could not be saved");
        return;
      }
      setError(null);
      onSaved({ id: result.id, name: result.name ?? "Your map" });
    });
  }

  return (
    <form
      onSubmit={submit}
      className="space-y-3 rounded-md border border-border-muted p-3"
      aria-labelledby={`${id}-title`}
      data-testid="column-mapper"
    >
      <div>
        <h3 id={`${id}-title`} className="text-xs font-medium text-text-primary">
          Map Columns Yourself
        </h3>
        <p className="mt-1 text-2xs text-text-tertiary">
          Pick the header in your file for each field. A date comes from the trade date or the
          execution time; without a trade ID StockViz derives one from each row. Only the header
          names are saved.
        </p>
      </div>
      {headers.length === 0 ? (
        <p className="text-xs text-text-tertiary">Reading the file&apos;s header row…</p>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        {MAP_FIELDS.filter((f) => market === "in" || f.field !== "isin").map((f) => (
          <div key={f.field} className="grid gap-1.5">
            <Label htmlFor={`${id}-${f.field}`} className="text-xs">
              {f.label}
              {f.required ? null : <span className="text-text-tertiary"> (Optional)</span>}
            </Label>
            <select
              id={`${id}-${f.field}`}
              name={`field_${f.field}`}
              value={values[f.field] ?? ""}
              onChange={(e) => setValues((prev) => ({ ...prev, [f.field]: e.target.value }))}
              className={SELECT}
            >
              <option value="">Not in File</option>
              {headers.map((h) => (
                <option key={h} value={h}>
                  {h}
                </option>
              ))}
            </select>
          </div>
        ))}
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-date-order`} className="text-xs">
            Dates Like 03/04/2025 Are
          </Label>
          <select id={`${id}-date-order`} name="date_order" defaultValue="auto" className={SELECT}>
            <option value="auto">Worked Out From the File</option>
            <option value="day_first">Day First (3 April)</option>
            <option value="month_first">Month First (March 4)</option>
          </select>
        </div>
        {market === "in" ? (
          <div className="grid gap-1.5">
            <Label htmlFor={`${id}-default-exchange`} className="text-xs">
              Exchange When the File Has None
            </Label>
            <select
              id={`${id}-default-exchange`}
              name="default_exchange"
              defaultValue=""
              className={SELECT}
            >
              <option value="">None (Reject Such Rows)</option>
              <option value="NSE">NSE</option>
              <option value="BSE">BSE</option>
            </select>
          </div>
        ) : (
          <input type="hidden" name="default_exchange" value="" />
        )}
        <div className="grid gap-1.5 sm:col-span-2">
          <Label htmlFor={`${id}-name`} className="text-xs">
            Map Name
          </Label>
          <Input
            id={`${id}-name`}
            name="map_name"
            maxLength={60}
            required
            defaultValue={market === "us" ? "My US Broker" : "My Broker"}
          />
        </div>
      </div>
      {error ? (
        <p role="alert" className="text-xs text-loss">
          {error}
        </p>
      ) : null}
      <Button type="submit" size="sm" disabled={pending || headers.length === 0}>
        {pending ? "Saving…" : "Save Map and Preview"}
      </Button>
    </form>
  );
}

function SavedMaps({ maps }: { maps: SavedImportMap[] }) {
  const [state, action, pending] = useActionState(deleteImportMapAction, INITIAL);
  if (maps.length === 0) return null;
  return (
    <section aria-label="Your column maps" className={`${CARD} space-y-2 p-4 text-xs`}>
      <h2 className="text-sm font-medium text-text-primary">Your Column Maps</h2>
      <ul className="divide-y divide-border-muted rounded-md border border-border-muted">
        {maps.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
            <span className="text-text-primary">{m.name}</span>
            <span className="text-text-tertiary">
              {Object.keys(m.mapping).length} fields
              {m.default_exchange ? ` · default ${m.default_exchange}` : ""}
            </span>
            <form action={action} className="ml-auto">
              <input type="hidden" name="map_id" value={m.id} />
              <Button type="submit" size="sm" variant="ghost" disabled={pending}>
                Delete
              </Button>
            </form>
          </li>
        ))}
      </ul>
      <ActionMessage state={state} />
    </section>
  );
}

function PreviewPanel({
  preview,
  busy,
  onConfirm,
  market,
  currency,
}: {
  preview: ImportPreview;
  busy: boolean;
  onConfirm: () => void;
  market: Market;
  currency: string;
}) {
  const money = (value: string | number) => formatCurrency(Number(value), currency);
  const skipped = preview.problems.filter((x) => problemSkipsRow(x.kind as ProblemKind));
  const flagged = preview.problems.filter((x) => !problemSkipsRow(x.kind as ProblemKind));
  return (
    <div className="space-y-4">
      <dl className="flex flex-wrap gap-x-5 gap-y-2 text-xs">
        {countItems(preview.counts).map((item) => (
          <div key={item.label} className="flex items-baseline gap-1.5">
            <dt className="text-text-tertiary">{item.label}</dt>
            <dd className="font-mono tabular-nums text-text-primary">{item.value}</dd>
          </div>
        ))}
      </dl>
      {preview.message ? <p className="text-xs text-text-secondary">{preview.message}</p> : null}

      <details className={CARD} open={preview.missing_required.length > 0}>
        <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-text-secondary">
          Columns Matched ({preview.columns.filter((c) => c.header).length} of{" "}
          {preview.columns.length}) · {preview.format_label || preview.format}
        </summary>
        <div className="overflow-x-auto px-3 pb-3">
          <p className="mb-2 text-2xs text-text-tertiary" data-testid="map-used">
            Map used: <span className="text-text-secondary">{preview.format_label}</span> (
            {STATUS_LABEL[preview.format_status] ?? preview.format_status},{" "}
            {DETECTED_LABEL[preview.detected ?? "header"]}).{" "}
            {preview.format_status === "custom" ? null : preview.format_note}
            {preview.format_source ? ` Source: ${preview.format_source}.` : ""}
          </p>
          <table className="w-full min-w-[22rem] text-xs">
            <thead className="text-left text-2xs text-text-tertiary">
              <tr>
                <th className="py-1 pr-3 font-normal">Field</th>
                <th className="py-1 pr-3 font-normal">Header in Your File</th>
              </tr>
            </thead>
            <tbody>
              {preview.columns.map((c) => (
                <tr key={c.field} className="border-t border-border-muted">
                  <td className="py-1 pr-3">
                    {c.label}
                    {c.required ? null : <span className="text-text-tertiary"> (optional)</span>}
                  </td>
                  <td className="py-1 pr-3 font-mono">
                    {c.header ?? (
                      <span className={c.required ? "text-loss" : "text-text-tertiary"}>
                        {c.required ? "missing" : "not in file"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {preview.unmatched_headers.length > 0 ? (
            <p className="mt-2 text-2xs text-text-tertiary">
              Ignored headers: {preview.unmatched_headers.join(", ")}
            </p>
          ) : null}
        </div>
      </details>

      {preview.sample.length > 0 ? (
        <div className={CARD}>
          <h3 className="px-3 pt-2 text-xs font-medium text-text-secondary">
            First {preview.sample.length} of {preview.counts.new} New Trades
          </h3>
          <div className="overflow-x-auto px-3 pb-3">
            <table className="w-full min-w-[40rem] text-xs">
              <thead className="text-left text-2xs text-text-tertiary">
                <tr>
                  <th className="py-1 pr-3 font-normal">Row</th>
                  <th className="py-1 pr-3 font-normal">Symbol</th>
                  <th className="py-1 pr-3 font-normal">Side</th>
                  <th className="py-1 pr-3 text-right font-normal">Qty</th>
                  <th className="py-1 pr-3 text-right font-normal">Price</th>
                  <th className="py-1 pr-3 font-normal">Executed</th>
                  <th className="py-1 pr-3 text-right font-normal">Est. Charges</th>
                  <th className="py-1 font-normal">Note</th>
                </tr>
              </thead>
              <tbody>
                {preview.sample.map((t) => {
                  const restated =
                    Number(t.restated_quantity) !== Number(t.quantity) ||
                    Number(t.restated_price) !== Number(t.price);
                  return (
                    <tr key={t.row} className="border-t border-border-muted">
                      <td className="py-1 pr-3 font-mono tabular-nums text-text-tertiary">
                        {t.row}
                      </td>
                      <td className="py-1 pr-3 font-mono">{t.ticker}</td>
                      <td className={`py-1 pr-3 ${t.side === "buy" ? "text-gain" : "text-loss"}`}>
                        {t.side === "buy" ? "Buy" : "Sell"}
                      </td>
                      <td className="py-1 pr-3 text-right font-mono tabular-nums">
                        {Number(t.quantity)}
                      </td>
                      <td className="py-1 pr-3 text-right font-mono tabular-nums" data-financial>
                        {money(t.price)}
                      </td>
                      <td className="py-1 pr-3 whitespace-nowrap">
                        {dateTime(t.executed_at, t.time_known, market)}
                      </td>
                      <td className="py-1 pr-3 text-right font-mono tabular-nums" data-financial>
                        {market === "us" ? "—" : money(t.fees)}
                      </td>
                      <td className="py-1 text-text-tertiary">
                        {[
                          t.product ? PRODUCT_LABELS[t.product] : null,
                          restated
                            ? `Split-adjusted ${Number(t.restated_quantity)} @ ${money(t.restated_price)}`
                            : null,
                          t.intraday_short ? "Intraday short" : null,
                          t.status === "needs_opening_lot" ? "Needs opening lot" : null,
                          t.basis_uncertain ? "Basis uncertain" : null,
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="px-3 pb-3 text-2xs leading-relaxed text-text-tertiary">
            {preview.fees_note}
          </p>
        </div>
      ) : null}

      {skipped.length > 0 || flagged.length > 0 ? (
        <div className={CARD}>
          <h3 className="px-3 pt-2 text-xs font-medium text-text-secondary">
            Problems ({preview.problems_total})
          </h3>
          <ul className="divide-y divide-border-muted px-3 pb-2 text-xs">
            {[...skipped, ...flagged].map((x) => (
              <li
                key={`${x.row}-${x.kind}`}
                className="flex flex-col gap-0.5 py-1.5 sm:flex-row sm:gap-3"
              >
                <span className="shrink-0 font-mono tabular-nums text-text-tertiary sm:w-16">
                  Row {x.row}
                </span>
                <span
                  className={`shrink-0 sm:w-44 ${problemSkipsRow(x.kind as ProblemKind) ? "text-loss" : "text-text-secondary"}`}
                >
                  {PROBLEM_LABELS[x.kind as ProblemKind]}
                  {x.symbol ? <span className="font-mono"> · {x.symbol}</span> : null}
                </span>
                <span className="text-text-tertiary">{x.reason}</span>
              </li>
            ))}
          </ul>
          {preview.problems_total > preview.problems.length ? (
            <p className="px-3 pb-2 text-2xs text-text-tertiary">
              Showing the first {preview.problems.length}.
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <Button type="button" onClick={onConfirm} disabled={!preview.can_commit || busy}>
          {busy ? "Importing…" : `Confirm Import (${preview.counts.new})`}
        </Button>
        <p className="text-2xs text-text-tertiary">
          Rows marked in red are left out. Sells that need an opening lot are kept and post once you
          add one.
        </p>
      </div>
    </div>
  );
}

function NeedsOpeningLot({ status, market }: { status: ImportsStatus; market: Market }) {
  if (status.needs_opening_lot.length === 0) return null;
  return (
    <section
      aria-label="Sells waiting for an opening lot"
      className="rounded-lg border border-loss/30 bg-loss/5 p-4 text-xs"
    >
      <h2 className="text-sm font-medium text-text-primary">Sells Waiting for an Opening Lot</h2>
      <p className="mt-1 text-text-tertiary">
        These sells have fewer shares bought before them in this book, so they are not posted. Add
        an opening lot for shares you held before the file&apos;s first trade.
      </p>
      <ul className="mt-2 space-y-1">
        {status.needs_opening_lot.map((n) => (
          <li key={n.ticker} className="flex flex-wrap gap-x-3">
            <span className="font-mono text-text-primary">{n.ticker}</span>
            <span className="text-text-secondary">
              {n.fills} sell{n.fills === 1 ? "" : "s"}, the first on{" "}
              {dateTime(n.first_sell_at, true, market)}
            </span>
            <span className="text-text-tertiary">short by {Number(n.short_by)} shares</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function OpeningLots({
  bookId,
  status,
  market,
  currency,
}: {
  bookId: number;
  status: ImportsStatus;
  market: Market;
  currency: string;
}) {
  const id = useId();
  const money = (value: string | number) => formatCurrency(Number(value), currency);
  const [state, action, pending] = useActionState(addOpeningLotAction, INITIAL);
  const suggested = status.needs_opening_lot[0]?.ticker ?? "";
  return (
    <section aria-labelledby={`${id}-title`} className={`${CARD} space-y-3 p-4`}>
      <div>
        <h2 id={`${id}-title`} className="text-sm font-medium text-text-primary">
          Opening Lots
        </h2>
        <p className="mt-1 text-xs text-text-tertiary">
          Shares you held before the tradebook&apos;s window, at their average price. A lot counts
          from the start of its date and carries no charges.
        </p>
      </div>
      {status.opening_lots.length > 0 ? (
        <ul className="divide-y divide-border-muted rounded-md border border-border-muted text-xs">
          {status.opening_lots.map((lot) => (
            <li key={lot.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
              <span className="font-mono text-text-primary">{lot.ticker}</span>
              <span className="font-mono tabular-nums">{Number(lot.quantity)} shares</span>
              <span className="font-mono tabular-nums" data-financial>
                @ {money(lot.avg_price)}
              </span>
              <span className="text-text-tertiary">
                from {dateTime(`${lot.on}T12:00:00Z`, false, market)}
              </span>
              <RemoveLot bookId={bookId} lotId={lot.id} />
            </li>
          ))}
        </ul>
      ) : null}
      <form action={action} className="grid gap-3 sm:grid-cols-5 sm:items-end">
        <input type="hidden" name="book_id" value={bookId} />
        <div className="grid gap-1.5 sm:col-span-2">
          <Label htmlFor={`${id}-ticker`} className="text-xs">
            Symbol
          </Label>
          <Input
            id={`${id}-ticker`}
            name="ticker"
            defaultValue={suggested}
            placeholder={market === "us" ? "AAPL" : "TCS.NS"}
            required
            autoCapitalize="characters"
            className="font-mono"
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-on`} className="text-xs">
            Held From
          </Label>
          <Input id={`${id}-on`} name="on" type="date" required />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-qty`} className="text-xs">
            Quantity
          </Label>
          <Input
            id={`${id}-qty`}
            name="quantity"
            type="number"
            inputMode="numeric"
            min="1"
            step="1"
            required
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${id}-avg`} className="text-xs">
            Average Price ({currency === "USD" ? "$" : "₹"})
          </Label>
          <Input
            id={`${id}-avg`}
            name="avg_price"
            type="number"
            inputMode="decimal"
            min="0.01"
            step="0.01"
            required
          />
        </div>
        <div className="sm:col-span-5">
          <Button type="submit" variant="outline" disabled={pending}>
            {pending ? "Adding…" : "Add Opening Lot"}
          </Button>
        </div>
      </form>
      <ActionMessage state={state} />
    </section>
  );
}

function RemoveLot({ bookId, lotId }: { bookId: number; lotId: number }) {
  const [state, action, pending] = useActionState(deleteOpeningLotAction, INITIAL);
  return (
    <form action={action} className="ml-auto">
      <input type="hidden" name="book_id" value={bookId} />
      <input type="hidden" name="lot_id" value={lotId} />
      <Button type="submit" size="sm" variant="ghost" disabled={pending}>
        Remove
      </Button>
      {state.error ? <span className="ml-2 text-loss">{state.error}</span> : null}
    </form>
  );
}

function BatchHistory({
  bookId,
  batches,
  market,
}: {
  bookId: number;
  batches: ImportBatch[];
  market: Market;
}) {
  const id = useId();
  // One action for every row: the outcome outlives the deleted row.
  const [state, action, pending] = useActionState(deleteImportAction, INITIAL);
  return (
    <section aria-labelledby={`${id}-title`} className={`${CARD} p-4`}>
      <h2 id={`${id}-title`} className="text-sm font-medium text-text-primary">
        Import History
      </h2>
      {batches.length === 0 ? (
        <p className="mt-2 text-xs text-text-tertiary">No imports yet.</p>
      ) : (
        <ul className="mt-3 divide-y divide-border-muted rounded-md border border-border-muted">
          {batches.map((b) => (
            <BatchRow
              key={b.id}
              bookId={bookId}
              batch={b}
              action={action}
              pending={pending}
              market={market}
            />
          ))}
        </ul>
      )}
      <div aria-live="polite" className="mt-2">
        <ActionMessage state={state} />
      </div>
    </section>
  );
}

function BatchRow({
  bookId,
  batch,
  action,
  pending,
  market,
}: {
  bookId: number;
  batch: ImportBatch;
  action: (formData: FormData) => void;
  pending: boolean;
  market: Market;
}) {
  const [confirming, setConfirming] = useState(false);
  const span =
    batch.first_trade_at && batch.last_trade_at
      ? `${dateTime(batch.first_trade_at, false, market)} to ${dateTime(batch.last_trade_at, false, market)}`
      : null;
  return (
    <li className="space-y-2 px-3 py-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-text-primary">
          Imported {dateTime(batch.created_at, true, market)}
        </span>
        <span className="font-mono tabular-nums text-text-secondary">
          {batch.rows_added} added · {batch.posted} posted
          {batch.needs_opening_lot ? ` · ${batch.needs_opening_lot} waiting` : ""}
        </span>
        <span className="text-text-tertiary">
          of {batch.rows_total} rows
          {batch.rows_duplicate ? `, ${batch.rows_duplicate} duplicate` : ""}
          {batch.rows_unmatched ? `, ${batch.rows_unmatched} unknown` : ""}
          {batch.rows_skipped_segment ? `, ${batch.rows_skipped_segment} F&O` : ""}
          {batch.column_map.startsWith("custom_") ? " · your map" : ""}
          {batch.rows_rejected ? `, ${batch.rows_rejected} rejected` : ""}
        </span>
        {!confirming ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="ml-auto"
            onClick={() => setConfirming(true)}
          >
            <Trash2 className="size-3.5" aria-hidden /> Delete
          </Button>
        ) : null}
      </div>
      {span ? <p className="text-2xs text-text-tertiary">Trades from {span}</p> : null}
      {confirming ? (
        <form
          action={action}
          className="flex flex-col gap-2 rounded-md border border-loss/30 bg-loss/5 p-2.5 sm:flex-row sm:items-center"
        >
          <input type="hidden" name="book_id" value={bookId} />
          <input type="hidden" name="batch_id" value={batch.id} />
          <p className="flex-1 text-text-secondary">
            Delete this import? Its {batch.fills} trade{batch.fills === 1 ? "" : "s"} leave the book
            and positions are rebuilt from the rest. This can&apos;t be undone.
          </p>
          <div className="flex gap-2">
            <Button type="submit" size="sm" variant="destructive" disabled={pending} autoFocus>
              {pending ? "Deleting…" : "Delete Import"}
            </Button>
            <Button type="button" size="sm" variant="outline" onClick={() => setConfirming(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}
    </li>
  );
}

function ActionMessage({ state }: { state: ImportActionState }) {
  if (state.error) {
    return (
      <p role="alert" className="text-xs text-loss">
        {state.error}
      </p>
    );
  }
  if (state.ok) return <p className="text-xs text-text-secondary">{state.ok}</p>;
  return null;
}
