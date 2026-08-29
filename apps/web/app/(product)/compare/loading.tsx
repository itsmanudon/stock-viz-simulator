export default function Loading() {
  return (
    <div className="w-full px-4 py-8 sm:px-6 xl:px-8">
      <div className="h-8 w-40 animate-pulse bg-surface-secondary" />
      <div className="mt-3 h-4 w-96 max-w-full animate-pulse bg-surface-secondary" />
      <div className="mt-8 h-[320px] animate-pulse bg-surface-secondary" />
      <span className="sr-only">Loading compare workspace…</span>
    </div>
  );
}
