/**
 * Building blocks for /docs pages. Server components, Aurora tokens only, no
 * prose plugin: each block sets its own type so pages read the same.
 */

import { ArrowLeft, ArrowRight, Info } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { type DocPage, neighbours } from "@/lib/docs/nav";

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

export function DocArticle({
  page,
  children,
}: {
  page: DocPage;
  children: ReactNode;
}) {
  const { previous, next } = neighbours(page.slug);
  return (
    <article className="min-w-0" aria-labelledby="doc-title">
      <h1 id="doc-title" className="text-3xl font-semibold tracking-[-0.025em] sm:text-4xl">
        {page.title}
      </h1>
      <p className="mt-3 max-w-2xl text-lg leading-8 text-text-secondary text-pretty">
        {page.summary}
      </p>
      <div className="mt-8 space-y-10">{children}</div>
      <nav
        aria-label="Previous and next pages"
        className="mt-14 grid gap-3 border-t border-border-muted pt-6 sm:grid-cols-2"
      >
        {previous ? (
          <Link
            href={`/docs/${previous.slug}`}
            className="group rounded-xl border border-border-muted px-4 py-3 hover:border-border"
          >
            <span className="flex items-center gap-1.5 text-sm text-text-tertiary">
              <ArrowLeft className="size-3" aria-hidden /> Previous
            </span>
            <span className="mt-1 block text-sm font-medium">{previous.title}</span>
          </Link>
        ) : (
          <span />
        )}
        {next ? (
          <Link
            href={`/docs/${next.slug}`}
            className="group rounded-xl border border-border-muted px-4 py-3 text-right hover:border-border"
          >
            <span className="flex items-center justify-end gap-1.5 text-sm text-text-tertiary">
              Next <ArrowRight className="size-3" aria-hidden />
            </span>
            <span className="mt-1 block text-sm font-medium">{next.title}</span>
          </Link>
        ) : null}
      </nav>
    </article>
  );
}

export function DocSection({ title, children }: { title: string; children: ReactNode }) {
  const id = slugify(title);
  return (
    <section aria-labelledby={id} className="scroll-mt-24 space-y-4">
      <h2 id={id} className="text-xl font-semibold tracking-tight">
        <a href={`#${id}`} className="hover:text-brand focus-visible:text-brand">
          {title}
        </a>
      </h2>
      {children}
    </section>
  );
}

export function H3({ children }: { children: ReactNode }) {
  return <h3 className="pt-2 text-base font-semibold">{children}</h3>;
}

export function P({ children }: { children: ReactNode }) {
  return <p className="max-w-3xl leading-7 text-text-secondary">{children}</p>;
}

export function List({ children, ordered = false }: { children: ReactNode; ordered?: boolean }) {
  const Tag = ordered ? "ol" : "ul";
  return (
    <Tag
      className={`max-w-3xl space-y-2 pl-5 leading-7 text-text-secondary ${
        ordered ? "list-decimal" : "list-disc"
      } marker:text-text-tertiary`}
    >
      {children}
    </Tag>
  );
}

export function Li({ children }: { children: ReactNode }) {
  return <li>{children}</li>;
}

export function Callout({ title, children }: { title: string; children: ReactNode }) {
  return (
    <aside
      aria-label={title}
      className="max-w-3xl rounded-xl border border-border-muted bg-surface-secondary px-4 py-3"
    >
      <p className="flex items-center gap-2 text-sm font-medium">
        <Info className="size-4 text-brand" aria-hidden /> {title}
      </p>
      <div className="mt-1.5 text-sm leading-6 text-text-secondary">{children}</div>
    </aside>
  );
}

/** Term-and-meaning rows, for rules and figures. */
export function Terms({ children }: { children: ReactNode }) {
  return (
    <dl className="max-w-3xl divide-y divide-border-muted border-y border-border-muted">
      {children}
    </dl>
  );
}

export function Term({ name, children }: { name: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-3 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
      <dt className="text-sm font-medium">{name}</dt>
      <dd className="text-sm leading-6 text-text-secondary">{children}</dd>
    </div>
  );
}

/** A real screenshot from the app, with a caption saying what it shows. */
export function Shot({ src, alt, caption }: { src: string; alt: string; caption: string }) {
  return (
    <figure className="max-w-3xl">
      {/* Static images in /public/docs; plain img keeps them out of the image optimiser. */}
      <img
        src={src}
        alt={alt}
        loading="lazy"
        className="w-full rounded-xl border border-border-muted"
      />
      <figcaption className="mt-2 text-xs text-text-tertiary">{caption}</figcaption>
    </figure>
  );
}

export function DocLink({ href, children }: { href: string; children: ReactNode }) {
  return (
    <Link href={href} className="text-brand underline-offset-4 hover:underline">
      {children}
    </Link>
  );
}
