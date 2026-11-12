import { PageEmptyState } from "@/components/page-header";

/**
 * Shown in place of a research page when one visitor has asked for more than
 * its per-minute share (`lib/visitor-limit.ts`, audit RS-6). Other visitors
 * are not affected.
 */
export function VisitorLimitNotice({ retryAfterSeconds }: { retryAfterSeconds: number }) {
  const wait = retryAfterSeconds === 1 ? "1 second" : `${retryAfterSeconds} seconds`;
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-10">
      <PageEmptyState title="Too many requests">
        This page was loaded many times in the last minute from your address. Try again in {wait}.
      </PageEmptyState>
    </div>
  );
}
