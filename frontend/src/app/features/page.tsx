import Link from "next/link";
import {
  Trophy,
  Users,
  Bot,
  Shield,
  Target,
  Sparkles,
  Check,
} from "lucide-react";

const features = [
  {
    icon: Trophy,
    title: "Customizable Scoring",
    gradient: "from-gold-400 to-gold-600",
    description:
      "Every stat, every weight, every bonus — you decide. Build the exact scoring system your league deserves, from traditional PPR to wild custom formats.",
    points: [
      "Per-stat point values for passing, rushing, receiving, defense, and kicking",
      "Threshold bonuses (300+ yard passing games, 100+ yard rushing games, etc.)",
      "Fully custom rules with your own conditions and multipliers",
    ],
  },
  {
    icon: Users,
    title: "2-Man Teams",
    gradient: "from-blue-400 to-purple-500",
    description:
      "Partner up and co-manage a team. Two minds, one roster. Share the wins, split the losses, double the fun.",
    points: [
      "Both owners get full roster and lineup control",
      "Split commissioner communication and trade decisions",
      "Great for friends who want to draft together, not against each other",
    ],
  },
  {
    icon: Shield,
    title: "Conference Leagues",
    gradient: "from-red-400 to-orange-500",
    description:
      "6v6 conference battles. Your squad vs. the rival conference. League-wide rivalries that make every matchup personal.",
    points: [
      "Split your league into two head-to-head conferences",
      "Conference-wide standings alongside individual team records",
      "Built for larger leagues that want more structure than one big pool",
    ],
  },
  {
    icon: Target,
    title: "Coaches & Coordinators",
    gradient: "from-green-400 to-emerald-500",
    description:
      "Hire HC, OC, DC, and STC to boost your team. Coaching bonuses add a whole new strategic layer to fantasy football.",
    points: [
      "Four coaching slots per team: Head Coach, OC, DC, Special Teams",
      "Weekly performance bonuses added directly to your score",
      "Build a full front office, not just a roster",
    ],
  },
  {
    icon: Bot,
    title: "AI-Powered Analysis",
    gradient: "from-purple-400 to-pink-500",
    description:
      "Lineup optimization, trade evaluation, bet analysis — all powered by AI that considers your roster, scoring settings, and league standings.",
    points: [
      "Start/sit recommendations based on your actual scoring config",
      "Trade grades that account for both sides of the deal",
      "Freeform betting-angle analysis for any matchup you ask about",
    ],
  },
  {
    icon: Sparkles,
    title: "Everything Else You Love",
    gradient: "from-cyan-400 to-teal-500",
    description:
      "Snake drafts, live draft rooms, waivers, trades, and commissioner tools. The full fantasy experience, fully customizable.",
    points: [
      "Live draft room with pick timers, queueing, and mock draft auto-fill",
      "Priority-order waiver claims with commissioner-run processing",
      "Full commissioner controls: adjustments, trade veto, draft order",
    ],
  },
];

export default function FeaturesPage() {
  return (
    <div>
      {/* Hero */}
      <section className="relative overflow-hidden border-b border-surface-700">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-850 via-surface-900 to-surface-900" />
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[700px] h-[400px] bg-gold-400/5 rounded-full blur-3xl" />

        <div className="relative max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-20 text-center">
          <h1 className="text-4xl md:text-5xl font-bold tracking-tight mb-4">
            <span className="text-white">Built For Leagues That</span>{" "}
            <span className="bg-gradient-to-r from-gold-400 to-gold-200 bg-clip-text text-transparent">
              Want More
            </span>
          </h1>
          <p className="text-surface-400 text-lg max-w-2xl mx-auto">
            Every feature below ships in the platform today — nothing here is a
            roadmap promise.
          </p>
        </div>
      </section>

      {/* Feature list */}
      <section className="py-20 bg-surface-850">
        <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 space-y-6">
          {features.map((feature, i) => (
            <div
              key={feature.title}
              className={`flex flex-col md:flex-row gap-6 items-start bg-surface-800/50 border border-surface-700 rounded-2xl p-6 md:p-8 hover:border-gold-400/20 transition-all ${
                i % 2 === 1 ? "md:flex-row-reverse" : ""
              }`}
            >
              <div
                className={`w-14 h-14 rounded-2xl bg-gradient-to-br ${feature.gradient} p-3 shrink-0`}
              >
                <feature.icon className="w-full h-full text-white" />
              </div>
              <div className="flex-1">
                <h2 className="text-xl font-bold text-white mb-2">{feature.title}</h2>
                <p className="text-surface-400 text-sm leading-relaxed mb-4">
                  {feature.description}
                </p>
                <ul className="space-y-1.5">
                  {feature.points.map((point) => (
                    <li key={point} className="flex items-start gap-2 text-sm text-surface-300">
                      <Check className="w-4 h-4 text-gold-400 shrink-0 mt-0.5" />
                      {point}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="py-24 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-surface-900 via-surface-850 to-surface-900" />
        <div className="absolute bottom-0 left-1/2 -translate-x-1/2 w-[600px] h-[400px] bg-gold-400/5 rounded-full blur-3xl" />

        <div className="relative max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">
            Ready to Build Your{" "}
            <span className="text-gold-400">Perfect League?</span>
          </h2>
          <Link
            href="/register"
            className="inline-flex bg-gold-400 hover:bg-gold-300 text-surface-900 px-10 py-4 rounded-xl font-bold text-lg transition-all hover:shadow-xl hover:shadow-gold-400/30 hover:-translate-y-0.5 active:translate-y-0"
          >
            Get Started Free
          </Link>
        </div>
      </section>
    </div>
  );
}
