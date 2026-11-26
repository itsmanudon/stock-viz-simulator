"use client";

/**
 * NewsSearchShortcut: on /news, "/" outside a field focuses the headline
 * search (`#news-q`) instead of opening the command palette (news redesign,
 * 26 Nov 2026). Mounted with the filters, so it works on an empty result
 * too. It listens in the capture phase and stops the event there; ⌘K / Ctrl+K
 * still opens the palette. `data-ready` marks it hydrated for the e2e test.
 */

import { useEffect, useState } from "react";

function isTyping(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.tagName === "SELECT" ||
      target.isContentEditable)
  );
}

export function NewsSearchShortcut() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTyping(event.target)) return;
      const search = document.getElementById("news-q");
      if (!(search instanceof HTMLInputElement)) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      search.focus();
      search.select();
    };
    window.addEventListener("keydown", onKey, true);
    setReady(true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);
  return <span hidden data-testid="news-search-shortcut" data-ready={ready ? "true" : "false"} />;
}
