import Link from "next/link";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

import { BackButton } from "./back-button";

type SearchParams = Promise<{ callbackUrl?: string }>;

const SAFE_FALLBACK = "/";

function safeCallback(raw: string | undefined): string {
  if (!raw) return SAFE_FALLBACK;
  if (!raw.startsWith("/") || raw.startsWith("//")) return SAFE_FALLBACK;
  return raw;
}

export default async function SignInRequiredPage({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const { callbackUrl } = await searchParams;
  const target = safeCallback(callbackUrl);
  const signInHref = `/login?callbackUrl=${encodeURIComponent(target)}`;

  return (
    <div className="container mx-auto flex min-h-[calc(100vh-8rem)] items-center justify-center px-6 py-12">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Sign in required</CardTitle>
          <CardDescription>
            You need to be signed in to view this page. Sign in to continue, or head back to where
            you came from.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          <p>
            Don&apos;t have an account?{" "}
            <Link href="/signup" className="text-foreground underline">
              Sign up
            </Link>{" "}
            — it&apos;s free and starts you with a $100,000 paper portfolio.
          </p>
        </CardContent>
        <CardFooter className="flex flex-col gap-3">
          <Button asChild className="w-full">
            <Link href={signInHref}>Sign in</Link>
          </Button>
          <BackButton />
        </CardFooter>
      </Card>
    </div>
  );
}
