import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="w-full px-4 py-8 sm:px-6 xl:px-8">
      <output aria-live="polite" className="block space-y-6">
        <span className="sr-only">Loading charts…</span>
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-[420px] w-full" />
      </output>
    </div>
  );
}
