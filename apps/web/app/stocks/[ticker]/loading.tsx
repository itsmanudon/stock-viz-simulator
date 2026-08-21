import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <output className="mx-auto block max-w-6xl px-4 py-8" aria-live="polite">
      <span className="sr-only">Loading ticker details…</span>
      <Skeleton className="mb-2 h-9 w-40" />
      <Skeleton className="mb-6 h-5 w-64" />
      <Skeleton className="mb-6 h-[320px] w-full" />
      <div className="grid gap-4 md:grid-cols-2">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    </output>
  );
}
