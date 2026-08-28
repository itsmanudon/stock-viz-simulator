import Link from "next/link";

import { PageFrame } from "@/components/page-frame";

export default function ReplaySessionNotFound() {
  return (
    <PageFrame width="workstation" className="py-10">
      <h1 className="text-2xl font-semibold">Replay not found</h1>
      <p className="mt-2 max-w-xl text-sm leading-6 text-text-secondary">
        That session does not exist, or it belongs to another account.
      </p>
      <Link href="/replay" className="mt-4 inline-block text-sm underline-offset-4 hover:underline">
        Back to Replay Lab
      </Link>
    </PageFrame>
  );
}
