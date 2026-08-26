import { cn } from "@/lib/utils";

const widths = {
  workstation: "w-full px-4 py-8 sm:px-6 xl:px-8",
  content: "mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 xl:px-8",
  narrow: "mx-auto w-full max-w-xl px-4 py-8 sm:px-6",
} as const;

export function PageFrame({
  width = "content",
  className,
  children,
}: React.PropsWithChildren<{
  width?: keyof typeof widths;
  className?: string;
}>) {
  return <div className={cn(widths[width], className)}>{children}</div>;
}
