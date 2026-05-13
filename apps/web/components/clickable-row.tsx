"use client";

import { useRouter } from "next/navigation";

import { TableRow } from "@/components/ui/table";

type Props = React.ComponentPropsWithoutRef<typeof TableRow> & { href: string };

export function ClickableRow({ href, className = "", children, ...props }: Props) {
  const router = useRouter();
  return (
    <TableRow
      onClick={() => router.push(href)}
      className={`cursor-pointer ${className}`}
      {...props}
    >
      {children}
    </TableRow>
  );
}
