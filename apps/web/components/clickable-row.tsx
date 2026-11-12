"use client";

import { useRouter } from "next/navigation";

import { TableRow } from "@/components/ui/table";

type Props = React.ComponentPropsWithoutRef<typeof TableRow> & { href: string };

export function ClickableRow({ href, className = "", children, ...props }: Props) {
  const router = useRouter();
  return (
    <TableRow
      onClick={(event) => {
        // A control inside the row (the screener's compare checkbox, a link)
        // does its own thing; only a click on the row itself opens the page.
        const target = event.target as HTMLElement;
        if (target.closest("input, a, button, label, select, textarea")) return;
        router.push(href);
      }}
      className={`cursor-pointer ${className}`}
      {...props}
    >
      {children}
    </TableRow>
  );
}
