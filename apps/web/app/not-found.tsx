import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-lg flex-col items-start gap-4 px-4 py-24">
      <p className="font-mono text-sm text-muted-foreground">404</p>
      <h1 className="text-2xl font-bold">Page not found</h1>
      <p className="text-muted-foreground">
        That page doesn&apos;t exist. It may have moved, or the ticker may not be in our universe.
      </p>
      <div className="flex gap-3">
        <Button asChild>
          <Link href="/markets">Browse markets</Link>
        </Button>
        <Button asChild variant="ghost">
          <Link href="/">Go home</Link>
        </Button>
      </div>
    </div>
  );
}
