"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { isLoggedIn } from "@/lib/api-client";

/** Wrap a page that only makes sense for a signed-in user. Logged-out
 * visitors are sent to /login?next=<this page> (and see nothing of the
 * page meanwhile). Purely UX: the backend already 401s every mutation
 * these pages make without a token. Mirror image of RedirectIfLoggedIn. */
export default function RequireLogin({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [allowed, setAllowed] = useState<boolean | null>(null);

  useEffect(() => {
    const ok = isLoggedIn();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- localStorage is only readable after mount
    setAllowed(ok);
    if (!ok) router.replace(`/login?next=${encodeURIComponent(pathname || "/")}`);
  }, [router, pathname]);

  if (!allowed) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center text-surface-400 text-sm">
        {allowed === false ? "Redirecting to log in..." : "Loading..."}
      </div>
    );
  }
  return <>{children}</>;
}
