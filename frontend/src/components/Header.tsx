import Link from "next/link";

export default function Header() {
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
            <Link
              href="/dashboard"
              className="text-surface-300 hover:text-gold-400 transition-colors text-sm font-medium"
            >
              Dashboard
            </Link>
            <Link
              href="/features"
              className="text-surface-300 hover:text-gold-400 transition-colors text-sm font-medium"
            >
              Features
            </Link>
            <Link
              href="/leagues"
              className="text-surface-300 hover:text-gold-400 transition-colors text-sm font-medium"
            >
              Leagues
            </Link>
            <Link
              href="/ai-analysis"
              className="text-surface-300 hover:text-gold-400 transition-colors text-sm font-medium"
            >
              AI Analysis
            </Link>
          </nav>

          {/* Auth Buttons */}
          <div className="flex items-center gap-3">
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
          </div>
        </div>
      </div>
    </header>
  );
}
