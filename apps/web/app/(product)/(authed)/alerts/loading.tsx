import { TableSkeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="w-full px-4 py-8 sm:px-6 xl:px-8">
      <TableSkeleton label="Loading alerts…" />
    </div>
  );
}
