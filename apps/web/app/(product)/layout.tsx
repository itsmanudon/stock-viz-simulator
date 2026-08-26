import { auth } from "@/auth";
import { AppShell } from "@/components/app-shell";

export default async function ProductLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  return <AppShell signedIn={Boolean(session?.user?.id)}>{children}</AppShell>;
}
