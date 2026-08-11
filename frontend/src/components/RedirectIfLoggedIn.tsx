"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { isLoggedIn } from "@/lib/api-client";

// The homepage, /features, /login, and /register are all for people who
// either don't have an account yet or aren't authenticated right now --
// once you're logged in there's nothing for you on any of them, just
// /dashboard. isLoggedIn() only reads localStorage (no server-side session),
// so this can only run client-side after mount -- a logged-in visitor sees
// a brief flash of the page before this redirects. Accepted trade-off:
// that visitor is the rare case (most traffic on these pages is logged
// out), and avoiding the flash would mean gating the common case behind a
// loading spinner instead, which is worse.
export default function RedirectIfLoggedIn({ to = "/dashboard" }: { to?: string }) {
  const router = useRouter();

  useEffect(() => {
    if (isLoggedIn()) {
      router.replace(to);
    }
  }, [router, to]);

  return null;
}
