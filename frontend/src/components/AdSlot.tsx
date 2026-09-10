"use client";

import { useEffect, useRef } from "react";

// Google AdSense, gated behind env vars (2026-09-09) -- same "optional,
// off by default without a real value" convention this app already
// uses for Sentry (see .env.local.example: no DSN means the SDK never
// reports anything). Without NEXT_PUBLIC_ADSENSE_CLIENT_ID set at build
// time, this renders nothing at all -- not a placeholder box, not a
// collapsed-but-still-in-the-DOM element -- so flipping ads on later is
// a config change (set the env vars, redeploy), never a code change or
// a layout reshuffle. 11 new leagues in ~2 days is the growth signal
// that made turning this on worth having ready.
const ADSENSE_CLIENT_ID = process.env.NEXT_PUBLIC_ADSENSE_CLIENT_ID;
const ADSENSE_SLOT_ID = process.env.NEXT_PUBLIC_ADSENSE_SLOT_ID;

const ADSENSE_SCRIPT_SRC = "https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js";

declare global {
  interface Window {
    adsbygoogle?: unknown[];
  }
}

let scriptLoadPromise: Promise<void> | null = null;

/** Loads AdSense's script at most once per page, regardless of how many
 * AdSlot instances mount -- a second <script> tag for the same src is
 * harmless in practice, but there's no reason to add one per slot. */
function loadAdsenseScript(clientId: string): Promise<void> {
  if (scriptLoadPromise) return scriptLoadPromise;
  scriptLoadPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src^="${ADSENSE_SCRIPT_SRC}"]`);
    if (existing) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = `${ADSENSE_SCRIPT_SRC}?client=${encodeURIComponent(clientId)}`;
    script.async = true;
    script.crossOrigin = "anonymous";
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Failed to load AdSense script"));
    document.head.appendChild(script);
  });
  return scriptLoadPromise;
}

interface AdSlotProps {
  /** A short label for which placement this is, for debugging only --
   * never rendered. E.g. "league-page-bottom", "dashboard-bottom". */
  placement: string;
  className?: string;
}

/** Drop this anywhere a page has room for a horizontal ad unit. Renders
 * nothing (not even a wrapper div) when ads aren't configured, so a page
 * with ads off looks byte-for-byte the same as before this existed. */
export default function AdSlot({ placement, className }: AdSlotProps) {
  const insRef = useRef<HTMLModElement | null>(null);
  const pushedRef = useRef(false);

  useEffect(() => {
    if (!ADSENSE_CLIENT_ID || !ADSENSE_SLOT_ID) return;
    if (pushedRef.current) return; // React StrictMode double-invokes effects in dev -- never push twice for the same <ins>
    pushedRef.current = true;

    loadAdsenseScript(ADSENSE_CLIENT_ID)
      .then(() => {
        try {
          (window.adsbygoogle = window.adsbygoogle || []).push({});
        } catch {
          // AdSense throws if the script failed to fully initialize (ad
          // blocker, offline, etc.) -- never let that surface as a page
          // error for something this non-critical.
        }
      })
      .catch(() => {
        // Script failed to load (ad blocker, network) -- the <ins> just
        // stays empty, same as any blocked ad on any other site.
      });
  }, []);

  if (!ADSENSE_CLIENT_ID || !ADSENSE_SLOT_ID) return null;

  return (
    <div className={className} data-ad-placement={placement}>
      <ins
        ref={insRef}
        className="adsbygoogle"
        style={{ display: "block" }}
        data-ad-client={ADSENSE_CLIENT_ID}
        data-ad-slot={ADSENSE_SLOT_ID}
        data-ad-format="auto"
        data-full-width-responsive="true"
      />
    </div>
  );
}
