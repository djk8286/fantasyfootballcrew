import Link from "next/link";
import {
  Trophy,
  Users,
  Bot,
  Shield,
  Target,
  Sparkles,
} from "lucide-react";

const features = [
  {
    icon: Trophy,
    title: "Customizable Scoring",
    description:
      "Every stat, every weight, every bonus — you decide. Build the exact scoring system your league deserves, from traditional PPR to wild custom formats.",
    gradient: "from-gold-400 to-gold-600",
  },
  {
    icon: Users,
    title: "2-Man Teams",
    description:
      "Partner up and co-manage a team. Two minds, one roster. Share the wins, split the losses, double the fun.",
    gradient: "from-blue-400 to-purple-500",
  },
  {
    icon: Shield,
    title: "Conference Leagues",
    description:
      "6v6 conference battles. Your squad vs. the rival conference. League-wide rivalries that make every matchup personal.",
    gradient: "from-red-400 to-orange-500",
  },
  {
    icon: Target,
    title: "Coaches & Coordinators",
    description:
      "Hire HC, OC, DC, and STC to boost your team. Coaching bonuses add a whole new strategic layer to fantasy football.",
    gradient: "from-green-400 to-emerald-500",
  },
  {
    icon: Bot,
    title: "AI-Powered Analysis",
    description:
      "Lineup optimization, trade evaluation, bet analysis — all powered by AI that considers matchups, weather, and trends.",
    gradient: "from-purple-400 to-pink-500",
  },
  {
    icon: Sparkles,
    title: "Everything Else You Love",
    description:
      "Snake & auction drafts, waivers, trades, keepers, dynasty modes, and more. The full fantasy experience, fully customizable.",
    gradient: "from-cyan-400 to-teal-500",
  },
];

export default function Home() {
  return (
    <div>
      {/* Hero Section */}
      <section className="relative overflow-hidden">
        {/* Background gradient */}
        <div className="absolute inset-0 bg-gradient-to-b from-surface-900 via-surface-850 to-surface-900" />
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[600px] bg-gold-400/5 rounded-full blur-3xl" />

        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-24 md:py-32">
          <div className="text-center max-w-4xl mx-auto">
            {/* Beta badge */}
            <div className="inline-flex items-center gap-2 px-4 py-1.5 bg-gold-400/10 border border-gold-400/20 rounded-full mb-8">
              <span className="w-2 h-2 bg-gold-400 rounded-full animate-pulse" />
              <span className="text-gold-400 text-sm font-medium">
                Beta Coming August 2026
              </span>
            </div>

            <h1 className="text-4xl md:text-6xl lg:text-7xl font-bold tracking-tight mb-6">
              <span className="text-white">Fantasy Football,</span>
              <br />
              <span className="bg-gradient-to-r from-gold-400 to-gold-200 bg-clip-text text-transparent">
                Your Way
              </span>
            </h1>

            <p className="text-lg md:text-xl text-surface-300 max-w-2xl mx-auto mb-10 leading-relaxed">
              Custom scoring. 2-Man Teams. Conference Battles. Coaches &
              Coordinators. AI-Powered Analysis. The only limit is your
              imagination.
            </p>

            {/* CTA Buttons */}
            <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link
                href="/register"
                className="bg-gold-400 hover:bg-gold-300 text-surface-900 px-8 py-3.5 rounded-xl font-bold text-base transition-all hover:shadow-xl hover:shadow-gold-400/30 hover:-translate-y-0.5 active:translate-y-0"
              >
                Get Started Free
              </Link>
              <Link
                href="#features"
                className="border border-surface-600 hover:border-gold-400/50 text-surface-300 hover:text-gold-400 px-8 py-3.5 rounded-xl font-medium text-base transition-all"
              >
                See Features
              </Link>
            </div>

            {/* Stats */}
            <div className="grid grid-cols-3 gap-8 mt-20 max-w-lg mx-auto">
              <div>
                <div className="text-2xl md:text-3xl font-bold text-gold-400">
                  ∞
                </div>
                <div className="text-surface-500 text-sm mt-1">
                  Scoring Combos
                </div>
              </div>
              <div>
                <div className="text-2xl md:text-3xl font-bold text-gold-400">
                  🏆
                </div>
                <div className="text-surface-500 text-sm mt-1">
                  League Types
                </div>
              </div>
              <div>
                <div className="text-2xl md:text-3xl font-bold text-gold-400">
                  🤖
                </div>
                <div className="text-surface-500 text-sm mt-1">
                  AI Analysis
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="py-24 bg-surface-850">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">
              Everything You Need.{" "}
              <span className="text-gold-400">Nothing You Don&apos;t.</span>
            </h2>
            <p className="text-surface-400 text-lg max-w-2xl mx-auto">
              FantasyFootballCrew is built from the ground up for leagues that
              want to do things differently.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map((feature) => (
              <div
                key={feature.title}
                className="group relative bg-surface-800/50 border border-surface-700 rounded-2xl p-6 hover:border-gold-400/20 transition-all hover:-translate-y-1 hover:shadow-xl hover:shadow-gold-400/5"
              >
                <div
                  className={`w-12 h-12 rounded-xl bg-gradient-to-br ${feature.gradient} p-2.5 mb-4`}
                >
                  <feature.icon className="w-full h-full text-white" />
                </div>
                <h3 className="text-lg font-semibold text-white mb-2 group-hover:text-gold-400 transition-colors">
                  {feature.title}
                </h3>
                <p className="text-surface-400 text-sm leading-relaxed">
                  {feature.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-24 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-900 via-surface-850 to-surface-900" />
        <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[600px] h-[400px] bg-gold-400/5 rounded-full blur-3xl" />

        <div className="relative max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">
            Ready to Build Your{" "}
            <span className="text-gold-400">Perfect League?</span>
          </h2>
          <p className="text-surface-400 text-lg mb-8">
            Beta launches August 2026. Sign up now and be the first to draft
            when we go live.
          </p>
          <Link
            href="/register"
            className="inline-flex bg-gold-400 hover:bg-gold-300 text-surface-900 px-10 py-4 rounded-xl font-bold text-lg transition-all hover:shadow-xl hover:shadow-gold-400/30 hover:-translate-y-0.5 active:translate-y-0"
          >
            Join the Waitlist
          </Link>
        </div>
      </section>
    </div>
  );
}
