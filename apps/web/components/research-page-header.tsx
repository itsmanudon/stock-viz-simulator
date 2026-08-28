import { PageEmptyState, PageHeader, PageSubnav } from "@/components/page-header";
import { RESEARCH_SUBNAV } from "@/lib/app-navigation";

/**
 * Research flavour of the shared page chrome — see `page-header.tsx`.
 * Only the fixed "Research" eyebrow and the subnav items differ.
 */
export function ResearchPageHeader({
  title,
  description,
  meta,
  actions,
}: {
  title: string;
  description: string;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <PageHeader
      eyebrow="Research"
      title={title}
      description={description}
      meta={meta}
      actions={actions}
    />
  );
}

export function ResearchSubnav({ current }: { current: string }) {
  return <PageSubnav items={RESEARCH_SUBNAV} current={current} label="Research tools" />;
}

export function ResearchEmptyState(props: {
  title: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return <PageEmptyState {...props} />;
}

export function ResearchSectionHeader({
  title,
  description,
  id,
}: {
  title: string;
  description?: string;
  id?: string;
}) {
  return (
    <div className="mb-3">
      <h2 id={id} className="text-sm font-semibold tracking-tight">
        {title}
      </h2>
      {description ? (
        <p className="mt-1 text-xs leading-5 text-text-tertiary">{description}</p>
      ) : null}
    </div>
  );
}
