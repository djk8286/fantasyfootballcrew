import Link from "next/link";

export default function Footer() {
  return (
    <footer className="border-t border-surface-700 bg-surface-900 py-12">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
          {/* Brand */}
          <div className="col-span-1 md:col-span-2">
            <Link href="/" className="flex items-center gap-2 mb-4">
              <div className="w-7 h-7 bg-gold-400 rounded flex items-center justify-center">
                <span className="text-surface-900 font-bold text-xs">FFC</span>
              </div>
              <span className="text-lg font-bold">
                <span className="text-white">Fantasy</span>
                <span className="text-gold-400">Football</span>
                <span className="text-white">Crew</span>
              </span>
            </Link>
            <p className="text-surface-400 text-sm max-w-sm">
              The most customizable fantasy football platform. Build your perfect
              league with unique scoring, 2-Man Teams, Conference Battles, and
              AI-powered analysis.
            </p>
          </div>

          {/* Quick Links */}
          <div>
            <h3 className="text-white font-semibold mb-3 text-sm uppercase tracking-wider">
              Product
            </h3>
            <ul className="space-y-2">
              <li>
                <Link
                  href="/features"
                  className="text-surface-400 hover:text-gold-400 text-sm transition-colors"
                >
                  Features
                </Link>
              </li>
              <li>
                <Link
                  href="/leagues"
                  className="text-surface-400 hover:text-gold-400 text-sm transition-colors"
                >
                  Leagues
                </Link>
              </li>
              <li>
                <Link
                  href="/ai-analysis"
                  className="text-surface-400 hover:text-gold-400 text-sm transition-colors"
                >
                  AI Analysis
                </Link>
              </li>
            </ul>
          </div>

          {/* Support */}
          <div>
            <h3 className="text-white font-semibold mb-3 text-sm uppercase tracking-wider">
              Company
            </h3>
            <ul className="space-y-2">
              <li>
                <Link
                  href="/about"
                  className="text-surface-400 hover:text-gold-400 text-sm transition-colors"
                >
                  About
                </Link>
              </li>
              <li>
                <Link
                  href="/contact"
                  className="text-surface-400 hover:text-gold-400 text-sm transition-colors"
                >
                  Contact
                </Link>
              </li>
              <li>
                <span className="text-surface-500 text-sm">
                  Beta 2026
                </span>
              </li>
            </ul>
          </div>
        </div>

        <div className="border-t border-surface-700 mt-8 pt-8 flex flex-col sm:flex-row justify-between items-center gap-4">
          <p className="text-surface-500 text-xs">
            &copy; {new Date().getFullYear()} FantasyFootballCrew. All rights
            reserved.
          </p>
          <p className="text-surface-600 text-xs">
            Built for the love of the game. 🏈
          </p>
        </div>
      </div>
    </footer>
  );
}
