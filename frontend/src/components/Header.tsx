"use client";

import Link from "next/link";
import { useState, useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Menu, X, Settings } from "lucide-react";
import { isLoggedIn, logout } from "@/lib/api-client";
import NotificationBell from "./NotificationBell";

const NAV_LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/mock-draft", label: "Mock Draft" },
  { href: "/features", label: "Features" },
  { href: "/leagues", label: "Leagues" },
  { href: "/ai-analysis", label: "AI Analysis" },
];

export default function Header() {
  const router = useRouter();
  const pathname = usePathname();
  const [loggedIn, setLoggedIn] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    setLoggedIn(isLoggedIn());
  }, []);

  // Header lives in the root layout, outside {children}, so it never
  // remounts on navigation -- close the mobile menu on route change so it
  // doesn't stay open over the new page.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  const handleLogout = () => {
    logout();
    setLoggedIn(false);
    setMenuOpen(false);
    router.push("/login");
  };

  return (
    <header className="border-b border-surface-700 bg-surface-900/80 backdrop-blur-md sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2">
            <div className="w-8 h-8 bg-gold-400 rounded-lg flex items-center justify-center">
              <span className="text-surface-900 font-bold text-sm">FFC</span>
            </div>
            <span className="text-xl font-bold">
              <span className="text-white">Fantasy</span>
              <span className="text-gold-400">Football</span>
              <span className="text-white">Crew</span>
            </span>
          </Link>

          {/* Navigation */}
          <nav className="hidden md:flex items-center gap-8">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="text-surface-300 hover:text-gold-400 transition-colors text-sm font-medium"
              >
                {link.label}
              </Link>
            ))}
          </nav>

          {/* Auth Buttons -- desktop only; folded into the mobile menu below
              instead of cramming a third cluster next to the logo + hamburger */}
          <div className="hidden md:flex items-center gap-1">
            {loggedIn ? (
              <>
                <NotificationBell />
                <Link
                  href="/settings"
                  className="text-surface-300 hover:text-white transition-colors p-2"
                  title="Account settings"
                  aria-label="Account settings"
                >
                  <Settings className="w-4 h-4" />
                </Link>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="text-surface-300 hover:text-white transition-colors text-sm font-medium px-4 py-2"
                >
                  Log Out
                </button>
              </>
            ) : (
              <>
                <Link
                  href="/login"
                  className="text-surface-300 hover:text-white transition-colors text-sm font-medium px-4 py-2"
                >
                  Log In
                </Link>
                <Link
                  href="/register"
                  className="bg-gold-400 hover:bg-gold-300 text-surface-900 px-5 py-2 rounded-lg font-semibold text-sm transition-all hover:shadow-lg hover:shadow-gold-400/25"
                >
                  Get Started
                </Link>
              </>
            )}
          </div>

          {/* Mobile: bell stays visible outside the collapsed hamburger menu
              (unlike Dashboard/Features/etc below) since it's time-sensitive
              -- burying it one tap deeper would defeat the point of a badge. */}
          {loggedIn && (
            <div className="md:hidden">
              <NotificationBell />
            </div>
          )}

          {/* Mobile menu toggle -- the nav/auth links above are display:none
              below md, so this is the only way to reach Dashboard/Features/
              Leagues/AI Analysis (or Log In/Out) on a phone. */}
          <button
            type="button"
            className="md:hidden text-surface-300 hover:text-white transition-colors p-2 -mr-2"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
          >
            {menuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
          </button>
        </div>
      </div>

      {/* Mobile menu panel */}
      {menuOpen && (
        <div className="md:hidden border-t border-surface-700 bg-surface-900/95 backdrop-blur-md">
          <nav className="max-w-7xl mx-auto px-4 sm:px-6 py-3 flex flex-col gap-1">
            {NAV_LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="text-surface-300 hover:text-gold-400 hover:bg-surface-800 transition-colors text-sm font-medium px-3 py-2.5 rounded-lg"
              >
                {link.label}
              </Link>
            ))}
            <div className="h-px bg-surface-700 my-2" />
            {loggedIn ? (
              <>
                <Link
                  href="/settings"
                  className="text-surface-300 hover:text-gold-400 hover:bg-surface-800 transition-colors text-sm font-medium px-3 py-2.5 rounded-lg flex items-center gap-2"
                >
                  <Settings className="w-4 h-4" /> Account Settings
                </Link>
                <button
                  type="button"
                  onClick={handleLogout}
                  className="text-left text-surface-300 hover:text-white hover:bg-surface-800 transition-colors text-sm font-medium px-3 py-2.5 rounded-lg"
                >
                  Log Out
                </button>
              </>
            ) : (
              <>
                <Link
                  href="/login"
                  className="text-surface-300 hover:text-white hover:bg-surface-800 transition-colors text-sm font-medium px-3 py-2.5 rounded-lg"
                >
                  Log In
                </Link>
                <Link
                  href="/register"
                  className="bg-gold-400 hover:bg-gold-300 text-surface-900 px-3 py-2.5 rounded-lg font-semibold text-sm text-center transition-all mt-1"
                >
                  Get Started
                </Link>
              </>
            )}
          </nav>
        </div>
      )}
    </header>
  );
}
