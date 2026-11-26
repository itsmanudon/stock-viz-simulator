import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { DocArticle } from "@/components/docs/docs-ui";
import { DOC_CONTENT } from "@/components/docs/pages";
import { DOC_PAGES, findDocPage } from "@/lib/docs/nav";

type Params = { params: Promise<{ slug: string }> };

/** Pages with a route of their own (A4.2: /docs/costs reads the API). */
const OWN_ROUTES = new Set(["costs"]);

export function generateStaticParams() {
  return DOC_PAGES.filter((page) => !OWN_ROUTES.has(page.slug)).map((page) => ({
    slug: page.slug,
  }));
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const page = findDocPage((await params).slug);
  if (!page) return {};
  return { title: `${page.title} · Docs`, description: page.summary };
}

export default async function DocRoute({ params }: Params) {
  const { slug } = await params;
  const page = findDocPage(slug);
  const Content = DOC_CONTENT[slug];
  if (!page || !Content) notFound();
  return (
    <DocArticle page={page}>
      <Content />
    </DocArticle>
  );
}
