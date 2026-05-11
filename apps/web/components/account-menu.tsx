/**
 * Account dropdown shown in the site header.
 *
 * Server component: ``auth()`` reads the session on every request. Logged-out
 * users get a "Sign in" link; logged-in users get an avatar dropdown with a
 * sign-out form-action button.
 */

import Link from "next/link";

import { signOutAction } from "@/app/(auth)/actions";
import { auth } from "@/auth";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

function initials(name: string | null | undefined, email: string | null | undefined): string {
  const source = (name ?? email ?? "?").trim();
  const parts = source.split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return source.slice(0, 2).toUpperCase();
}

export async function AccountMenu() {
  const session = await auth();

  if (!session?.user) {
    return (
      <Link
        href="/login"
        className="text-sm text-muted-foreground transition hover:text-foreground"
      >
        Sign in
      </Link>
    );
  }

  const { name, email, image } = session.user;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="rounded-full outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring"
        aria-label="Account menu"
      >
        <Avatar className="h-8 w-8">
          {image ? <AvatarImage src={image} alt={name ?? email ?? ""} /> : null}
          <AvatarFallback>{initials(name, email)}</AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col">
            <span className="text-sm font-medium">{name ?? "Account"}</span>
            {email ? <span className="text-xs text-muted-foreground">{email}</span> : null}
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/portfolio">Portfolio</Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/trades">Trade history</Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <form action={signOutAction}>
            <button type="submit" className="w-full text-left">
              Sign out
            </button>
          </form>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
