"use client";

/**
 * A5.3: "Import tradebook (CSV)" for an imported book. Choose the file, see
 * the preview (which columns matched, the first trades, every problem by row),
 * then Confirm import. The file stays in this component between the two
 * steps and is sent again at commit with the preview's SHA-256; the API
 * stores nothing at preview. Batch history (with a two-step delete), the
 * opening-lot form and the sells still waiting for one sit below.
 *
 * Keyboard: every control is a native input, button or link; the preview's
 * result is announced (`aria-live`). Phone: tables scroll sideways inside
 * their card, the forms stack.
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
  deleteOpeningLotAction,
  previewTradebookAction,
} from "@/app/(product)/(authed)/portfolio/import/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ImportBatch, ImportPreview, ImportsStatus } from "@/lib/api/imports";
import { formatCurrency } from "@/lib/portfolio-view-model";
import {
  PROBLEM_LABELS,
  PRODUCT_LABELS,
  type ProblemKind,
  checkTradebookFile,
  countItems,
  problemSkipsRow,
} from "@/lib/tradebook-import";

const CARD = "rounded-lg border border-border-muted bg-surface-secondary/30";
const INITIAL: ImportActionState = {};

function dateTime(iso: string, timeKnown = true): string {
  const d = new Date(/(Z|[+-]\d{2}:\d{2})$/.test(iso) ? iso : `${iso}Z`);
  const opts: Intl.DateTimeFormatOptions = timeKnown
    ? { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" }
    : { dateStyle: "medium", timeZone: "Asia/Kolkata" };
  return d.toLocaleString("en-IN", opts) + (timeKnown ? " IST" : "");
}

function money(value: string | number): string {
  return formatCurrency(Number(value), "INR");
}

export function TradebookImport({ bookId, status }: { bookId: number; status: ImportsStatus }) {
  return (
    <div className="space-y-6">
      <FormatNote note={status.format_note} />
      <UploadFlow bookId={bookId} />
      <NeedsOpeningLot status={status} />
      <OpeningLots bookId={bookId} status={status} />
      <BatchHistory bookId={bookId} batches={status.batches} />
      <p className="text-2xs leading-relaxed text-text-tertiary">
        StockViz keeps each trade&apos;s parsed fields and the file&apos;s fingerprint (SHA-256),
        never the file, its name or your client id. Deleting an import removes its trades for good;
        database backups still hold deleted rows until they age out.
      </p>
    </div>
  );
}

function FormatNote({ note }: { note: string }) {
  return (
    <p
      role="note"
      className="flex items-start gap-2 rounded-md border border-border-muted bg-surface-secondary/50 px-3 py-2.5 text-xs text-text-secondary"
    >
      <Info className="mt-px size-3.5 shrink-0 text-text-tertiary" aria-hidden />
      <span>
        <span className="font-medium text-text-primary">Format unconfirmed.</span> {note}
      </span>
    </p>
  );
}

function UploadFlow({ bookId }: { bookId: number }) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [preview, setPreview] = useState<PreviewState>({});
  const [commit, setCommit] = useState<CommitState>({});
  const [busy, start] = useTransition();

  function choose(next: File | null) {
    setPreview({});
    setCommit({});
    setFile(next);
    setFileError(next ? checkTradebookFile(next) : null);
  }

  function form(extra?: Record<string, string>): FormData {
    const data = new FormData();
    data.set("book_id", String(bookId));
    if (file) data.set("file", file);
    for (const [k, v] of Object.entries(extra ?? {})) data.set(k, v);
    return data;
  }

  function runPreview(event: React.FormEvent) {
    event.preventDefault();
    if (!file || fileError) return;
    setCommit({});
    start(async () => setPreview(await previewTradebookAction(form())));
  }

  function runCommit() {
    const sha = preview.preview?.file_sha256;
    if (!file || !sha) return;
    start(async () => {
      const result = await commitTradebookAction(form({ file_sha256: sha }));
      setCommit(result);
      if (result.result) {
        setPreview({});
        setFile(null);
        if (input.current) input.current.value = "";
      }
    });
  }

  const p = preview.preview;
  return (
    <section aria-labelledby={`${id}-title`} className={`${CARD} space-y-4 p-4`}>
      <div>
        <h2 id={`${id}-title`} className="text-sm font-medium text-text-primary">
          Import Tradebook (CSV)
        </h2>
        <p className="mt-1 text-xs leading-relaxed text-text-tertiary">
          In Zerodha Console, open Reports → Tradebook, choose the equity segment and a period of up
          to a year, and download it as CSV. Files up to 2 MB. F&amp;O trades are not imported yet.
        </p>
      </div>
      <form onSubmit={runPreview} className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <div className="grid flex-1 gap-1.5">
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
        <Button type="submit" disabled={!file || Boolean(fileError) || busy}>
          <FileUp className="size-4" aria-hidden />
          {busy && !p ? "Reading…" : "Preview"}
        </Button>
      </form>
      {fileError ? (
        <p id={`${id}-file-error`} role="alert" className="text-xs text-loss">
          {fileError}
        </p>
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
        {p ? <PreviewPanel preview={p} busy={busy} onConfirm={runCommit} /> : null}
      </div>
    </section>
  );
}

function PreviewPanel({
  preview,
  busy,
  onConfirm,
}: {
  preview: ImportPreview;
  busy: boolean;
  onConfirm: () => void;
}) {
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
          {preview.columns.length})
        </summary>
        <div className="overflow-x-auto px-3 pb-3">
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
                        {dateTime(t.executed_at, t.time_known)}
                      </td>
                      <td className="py-1 pr-3 text-right font-mono tabular-nums" data-financial>
                        {money(t.fees)}
                      </td>
                      <td className="py-1 text-text-tertiary">
                        {[
                          t.product ? PRODUCT_LABELS[t.product] : null,
                          restated
                            ? `Split-adjusted ${Number(t.restated_quantity)} @ ${money(t.restated_price)}`
                            : null,
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

function NeedsOpeningLot({ status }: { status: ImportsStatus }) {
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
              {n.fills} sell{n.fills === 1 ? "" : "s"}, the first on {dateTime(n.first_sell_at)}
            </span>
            <span className="text-text-tertiary">short by {Number(n.short_by)} shares</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function OpeningLots({ bookId, status }: { bookId: number; status: ImportsStatus }) {
  const id = useId();
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
                from {dateTime(`${lot.on}T00:00:00+05:30`, false)}
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
            placeholder="TCS.NS"
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
            Average Price (₹)
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

function BatchHistory({ bookId, batches }: { bookId: number; batches: ImportBatch[] }) {
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
            <BatchRow key={b.id} bookId={bookId} batch={b} action={action} pending={pending} />
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
}: {
  bookId: number;
  batch: ImportBatch;
  action: (formData: FormData) => void;
  pending: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const span =
    batch.first_trade_at && batch.last_trade_at
      ? `${dateTime(batch.first_trade_at, false)} to ${dateTime(batch.last_trade_at, false)}`
      : null;
  return (
    <li className="space-y-2 px-3 py-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-text-primary">Imported {dateTime(batch.created_at)}</span>
        <span className="font-mono tabular-nums text-text-secondary">
          {batch.rows_added} added · {batch.posted} posted
          {batch.needs_opening_lot ? ` · ${batch.needs_opening_lot} waiting` : ""}
        </span>
        <span className="text-text-tertiary">
          of {batch.rows_total} rows
          {batch.rows_duplicate ? `, ${batch.rows_duplicate} duplicate` : ""}
          {batch.rows_unmatched ? `, ${batch.rows_unmatched} unknown` : ""}
          {batch.rows_skipped_segment ? `, ${batch.rows_skipped_segment} F&O` : ""}
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
