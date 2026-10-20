"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Newspaper, Users } from "lucide-react";
import { playersApi, nflApi, isLoggedIn } from "@/lib/api-client";
import { projectionTile } from "@/lib/projection-label";
import { PositionChip } from "@/components/ui/Badge";

interface NewsItem {
  id: string;
  headline: string;
  url: string;
  source: string;
  published_at: string;
}

interface RosteredBy {
  team_id: string;
  team_name: string;
  league_id: string;
  league_name: string;
  is_mine: boolean;
}

interface PlayerDetail {
  id: string;
  first_name: string;
  last_name: string;
  position: string;
  team: string | null;
  number: number | null;
  age: number | null;
  bye_week: number | null;
  injury_status: string | null;
  avatar_url: string | null;
  headline_stats: Record<string, number> | null;
  season_points: number | null;
  season_points_year: number | null;
  projected_points: number | null;
  projected_week: number | null;
  projected_year: number | null;
  weekly_points: { week: number; points: number }[];
  weekly_points_year: number | null;
  news: NewsItem[];
  rostered_by: RosteredBy[] | null;
}

function timeAgo(iso: string): string {
  const t = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`).getTime();
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 60) return `${mins || 1}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

const STAT_LABELS: Record<string, string> = {
  pass_yd: "Pass Yds", pass_td: "Pass TD", pass_int: "INT", rush_yd: "Rush Yds", rush_td: "Rush TD",
  rec: "Rec", rec_yd: "Rec Yds", rec_td: "Rec TD", fgm: "FGM", xpm: "XPM", sack: "Sacks", int: "INT",
};

function Card({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="bg-surface-800 border border-surface-700 rounded-2xl p-5 sm:p-6">
      <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
        {icon}
        {title}
      </h2>
      {children}
    </section>
  );
}

export default function PlayerDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [player, setPlayer] = useState<PlayerDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    playersApi
      .detail(id)
      .then((d) => setPlayer(d as PlayerDetail))
      .catch(() => setError("Player not found"))
      .finally(() => setLoading(false));
  }, [id]);

  const [currentWeek, setCurrentWeek] = useState<number | null>(null);
  useEffect(() => {
    nflApi
      .getCurrentWeek()
      .then((w) => setCurrentWeek(w.season_type === "regular" ? w.week : null))
      .catch(() => setCurrentWeek(null));
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }
  if (error || !player) {
    return (
      <div className="min-h-screen bg-surface-900 flex flex-col items-center justify-center gap-3">
        <p className="text-surface-300">{error || "Player not found"}</p>
        <Link href="/players" className="text-gold-400 hover:text-gold-300 text-sm font-semibold">Back to players</Link>
      </div>
    );
  }

  const name = `${player.first_name} ${player.last_name}`;
  const maxWeekly = Math.max(1, ...player.weekly_points.map((w) => w.points));
  const injured = player.injury_status && player.injury_status !== "None";
  const stats = Object.entries(player.headline_stats || {}).filter(([, v]) => v != null);

  return (
    <div className="min-h-screen bg-surface-900">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        <Link href="/players" className="inline-flex items-center gap-1.5 text-surface-400 hover:text-white text-sm">
          <ArrowLeft className="w-4 h-4" /> All players
        </Link>

        {/* Header */}
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-5 sm:p-6 flex flex-col sm:flex-row sm:items-center gap-5">
          <div className="w-24 h-24 rounded-2xl bg-surface-900 border border-surface-700 overflow-hidden shrink-0">
            {player.avatar_url && (
              // eslint-disable-next-line @next/next/no-img-element -- Sleeper CDN headshot, same as PlayerAvatar
              <img src={player.avatar_url} alt={name} className="w-full h-full object-cover" />
            )}
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold text-white">{name}</h1>
              <PositionChip pos={player.position} />
              {injured && (
                <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-red-500/15 text-red-400 border border-red-500/30">
                  {player.injury_status}
                </span>
              )}
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-sm text-surface-400">
              <span>{player.team || "Free agent"}</span>
              {player.number != null && <span>#{player.number}</span>}
              {player.age != null && <span>Age {player.age}</span>}
              {player.bye_week != null && <span>Bye week {player.bye_week}</span>}
              {!injured && <span className="text-green-400/80">Healthy</span>}
            </div>
          </div>
          <div className="flex gap-6 sm:text-right">
            <div>
              <p className="text-[10px] uppercase tracking-wider text-surface-500">
                {player.season_points_year ? `${player.season_points_year} pts` : "Season pts"}
              </p>
              <p className="text-2xl font-bold text-gold-400">
                {player.season_points != null ? player.season_points.toFixed(1) : "—"}
              </p>
            </div>
            {player.projected_points != null && (() => {
              const tile = projectionTile(player.projected_points, player.projected_week, currentWeek, player.bye_week);
              return (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-surface-500">{tile.label}</p>
                  <p className="text-2xl font-bold text-white">{tile.value != null ? tile.value.toFixed(1) : "—"}</p>
                  {tile.note && <p className="text-[10px] text-surface-500">{tile.note}</p>}
                </div>
              );
            })()}
          </div>
        </div>
        <p className="text-[11px] text-surface-500 -mt-3">Fantasy points use the site&apos;s default scoring.</p>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <Card title={`Weekly fantasy points${player.weekly_points_year ? ` (${player.weekly_points_year})` : ""}`}>
              {player.weekly_points.length === 0 ? (
                <p className="text-surface-500 text-sm">No weekly stats synced for this player yet.</p>
              ) : (
                <ul className="space-y-1.5">
                  {player.weekly_points.map((w) => (
                    <li key={w.week} className="flex items-center gap-3 text-xs">
                      <span className="w-12 text-surface-400 shrink-0">Week {w.week}</span>
                      <div className="flex-1 h-2.5 bg-surface-900 rounded-full overflow-hidden">
                        <div className="h-full bg-gold-400/80 rounded-full" style={{ width: `${Math.max(0, (w.points / maxWeekly) * 100)}%` }} />
                      </div>
                      <span className="w-12 text-right text-white font-semibold shrink-0">{w.points.toFixed(1)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            {player.news.length > 0 && (
              <Card title="Recent news" icon={<Newspaper className="w-4 h-4 text-gold-400" />}>
                <ul className="divide-y divide-surface-700/60">
                  {player.news.map((n) => (
                    <li key={n.id} className="py-2.5 first:pt-0 last:pb-0">
                      <a href={n.url} target="_blank" rel="noopener noreferrer" className="text-sm text-white hover:text-gold-400 font-medium leading-snug">
                        {n.headline}
                      </a>
                      <div className="mt-0.5 text-[11px] text-surface-500">
                        {n.source} &middot; <time dateTime={n.published_at}>{timeAgo(n.published_at)}</time>
                      </div>
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>

          <div className="space-y-6">
            {stats.length > 0 && (
              <Card title={`Season stats${player.season_points_year ? ` (${player.season_points_year})` : ""}`}>
                <dl className="grid grid-cols-2 gap-3">
                  {stats.map(([k, v]) => (
                    <div key={k} className="bg-surface-900/60 rounded-lg px-3 py-2">
                      <dt className="text-[10px] uppercase tracking-wider text-surface-500">{STAT_LABELS[k] || k}</dt>
                      <dd className="text-white font-semibold">{Math.round(v * 10) / 10}</dd>
                    </div>
                  ))}
                </dl>
              </Card>
            )}

            <Card title="In your leagues" icon={<Users className="w-4 h-4 text-gold-400" />}>
              {player.rostered_by === null || !isLoggedIn() ? (
                <p className="text-surface-500 text-sm">
                  <Link href={`/login?next=${encodeURIComponent(`/players/${player.id}`)}`} className="text-gold-400 hover:text-gold-300 font-semibold">
                    Log in
                  </Link>{" "}
                  to see which teams in your leagues roster {player.first_name}.
                </p>
              ) : player.rostered_by.length === 0 ? (
                <p className="text-surface-400 text-sm">Not on a roster in any of your leagues.</p>
              ) : (
                <ul className="space-y-2">
                  {player.rostered_by.map((r) => (
                    <li key={r.team_id} className="text-sm">
                      <Link href={`/leagues/${r.league_id}/teams/${r.team_id}`} className="text-white hover:text-gold-400 font-medium">
                        {r.team_name}
                      </Link>
                      {r.is_mine && <span className="ml-1.5 text-[10px] font-bold text-gold-400 uppercase">Your team</span>}
                      <div className="text-[11px] text-surface-500">{r.league_name}</div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
