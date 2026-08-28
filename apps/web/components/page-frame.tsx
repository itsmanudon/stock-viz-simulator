import { cn } from "@/lib/utils";

const widths = {
  workstation: "w-full px-4 py-6 sm:px-6 lg:px-8 lg:py-7",
  content: "mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:py-7 xl:px-8",
  narrow: "mx-auto w-full max-w-xl px-4 py-7 sm:px-6",
} as const;

export function PageFrame({
  width = "content",
  className,
  children,
}: React.PropsWithChildren<{
  width?: keyof typeof widths;
  className?: string;
}>) {
  return <div className={cn("density-workspace", widths[width], className)}>{children}</div>;
}
