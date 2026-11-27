import { PageEmptyState, PageHeader, PageSubnav } from "@/components/page-header";
import { workspaceForPath, workspaceSubnav } from "@/lib/app-navigation";

/**
 * Research flavour of the shared page chrome — see `page-header.tsx`.
 * The subnav lists the page's workspace's routes (`lib/app-navigation.ts`).
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
  return <PageHeader title={title} description={description} meta={meta} actions={actions} />;
}

/** The current workspace's routes as tabs (A3.6: was one fixed Research list). */
export function ResearchSubnav({ current }: { current: string }) {
  const workspace = workspaceForPath(current);
  return (
    <PageSubnav
      items={workspaceSubnav(current)}
      current={current}
      label={`${workspace?.label ?? "Research"} tools`}
    />
  );
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
