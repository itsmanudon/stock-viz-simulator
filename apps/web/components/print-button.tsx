"use client";

/** A9.6: prints the page (the tearsheet); hidden on the printed copy. */

import { Button } from "@/components/ui/button";

export function PrintButton() {
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => window.print()}
      data-print-hide
    >
      Print or Save as PDF
    </Button>
  );
}
