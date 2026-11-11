import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ClosingCta } from "@/components/marketing/closing-cta";
import { LandingMotion } from "@/components/marketing/landing-motion";
import {
  OtherProductPages,
  ProductPage,
  findProductPage,
} from "@/components/marketing/product-page";

/**
 * /product/paper-trading, /product/research, /product/replay.
 *
 * Rendered per request like the rest of the public pages (the header reads
 * the session). Any other slug is a 404, including `news`, which waits for
 * the Aegis feed.
 */
type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const spec = findProductPage((await params).slug);
  if (!spec) return {};
  return {
    title: spec.name,
    description: spec.summary,
  };
}

export default async function ProductRoute({ params }: Params) {
  const spec = findProductPage((await params).slug);
  if (!spec) notFound();

  return (
    <div>
      <LandingMotion>
        <ProductPage spec={spec} />
        <OtherProductPages current={spec.slug} />
      </LandingMotion>
      <ClosingCta />
    </div>
  );
}
