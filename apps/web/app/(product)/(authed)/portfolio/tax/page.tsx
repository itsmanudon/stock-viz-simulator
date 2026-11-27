/**
 * /portfolio/tax — A7.12 (M10.7): the India capital gains estimate for an INR
 * book (`book`, default book when absent), one FY (`fy`) and an optional
 * surcharge band (`surcharge`). Every figure comes from `/v1/tax/india`.
 */

import type { Metadata } from "next";

import { IndiaTaxView } from "@/components/india-tax-view";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { AuthedApiError } from "@/lib/api/server";
import { getIndiaTax } from "@/lib/api/tax";
import { type IndiaTax, SURCHARGE_OPTIONS, TAX_YEARS, parseTaxParams } from "@/lib/india-tax";

export const metadata: Metadata = { title: "Capital gains" };

type Search = { fy?: string; surcharge?: string; book?: string };

function detailOf(err: AuthedApiError): string | null {
  try {
    const body = JSON.parse(err.detail) as { detail?: unknown };
    return typeof body.detail === "string" ? body.detail : null;
  } catch {
    return null;
  }
}

export default async function TaxPage({ searchParams }: { searchParams: Promise<Search> }) {
  const { fy, surcharge, book } = parseTaxParams(await searchParams);
  let data: IndiaTax | null = null;
  let error: string | null = null;
  try {
    data = await getIndiaTax(book, fy, surcharge);
  } catch (err) {
    if (err instanceof AuthedApiError && err.status === 409) {
      error = `${detailOf(err) ?? "This book is not covered"}. Pick an INR book with ?book=.`;
    } else if (err instanceof AuthedApiError && err.status === 404) {
      error = "That book is not yours or does not exist.";
    } else {
      error = "The estimate could not be loaded just now.";
    }
  }
  return (
    <div className="w-full space-y-6 px-4 py-6 sm:px-6 lg:py-7 xl:px-8">
      <PageHeader
        eyebrow="Portfolio & Tax"
        title="Capital gains"
        description="An estimate of India capital gains tax on listed equity for one book and financial year, by FIFO lots."
      />
      <form method="get" className="flex flex-wrap items-end gap-3" data-testid="tax-form">
        {book ? <input type="hidden" name="book" value={book} /> : null}
        <div className="space-y-1">
          <Label htmlFor="tax-fy" className="text-xs">
            Financial Year
          </Label>
          <select
            id="tax-fy"
            name="fy"
            defaultValue={fy}
            className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
          >
            {TAX_YEARS.map((y) => (
              <option key={y} value={y}>
                FY {y}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="tax-surcharge" className="text-xs">
            Surcharge Band
          </Label>
          <select
            id="tax-surcharge"
            name="surcharge"
            defaultValue={String(surcharge)}
            className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
          >
            {SURCHARGE_OPTIONS.map((o) => (
              <option key={o.value} value={String(o.value)}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <Button type="submit">Estimate</Button>
      </form>
      {error ? (
        <p className="text-sm text-text-secondary" data-testid="tax-error">
          {error}
        </p>
      ) : null}
      {data ? <IndiaTaxView data={data} /> : null}
    </div>
  );
}
