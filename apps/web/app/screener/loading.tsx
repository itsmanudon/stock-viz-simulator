import { TableSkeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <TableSkeleton label="Loading screener…" />
    </div>
  );
}
