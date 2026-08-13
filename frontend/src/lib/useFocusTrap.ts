"use client";

import { useEffect, useRef } from "react";

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea, input:not([disabled]), select, [tabindex]:not([tabindex="-1"])';

/**
 * Minimal focus trap + Escape-to-close for a modal/overlay. This app has
 * exactly two `fixed inset-0` overlays (AvatarPicker in leagues/[id]/
 * page.tsx, and MobileDraftRoom's queue sheet) and neither had any of
 * this -- focus could wander behind the visible overlay into the page
 * underneath, Escape did nothing, and a screen reader had no indication
 * either was a dialog at all.
 *
 * Moves focus into the dialog on mount, restores it to whatever was
 * focused before on unmount (so closing a modal doesn't strand focus at
 * the top of the page), keeps Tab/Shift+Tab cycling within the dialog,
 * and calls onClose on Escape. Attach the returned ref to the dialog's
 * outer container (give it `tabIndex={-1}` so it's a valid focus target
 * even when empty of its own focusable children) and pair with
 * `role="dialog" aria-modal="true"`.
 */
export function useFocusTrap<T extends HTMLElement>(onClose: () => void, active: boolean = true) {
  const containerRef = useRef<T | null>(null);

  useEffect(() => {
    if (!active) return;
    const container = containerRef.current;
    if (!container) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;

    const focusables = () => Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
    const first = focusables()[0];
    (first || container).focus();

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
        return;
      }
      if (e.key !== "Tab") return;
      const items = focusables();
      if (items.length === 0) return;
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onClose is
    // typically a fresh inline closure per render; re-running this whole
    // effect on every one of those would keep re-focusing the dialog and
    // fighting the user's own focus changes while it's open.
  }, [active]);

  return containerRef;
}
