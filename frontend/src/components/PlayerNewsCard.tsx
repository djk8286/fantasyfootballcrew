"use client";

import { useEffect, useState } from "react";
import { Bot } from "lucide-react";
import { teamNewsApi } from "@/lib/api-client";
import { Card, CardHeader } from "@/components/ui/Card";
import { SkeletonRows } from "@/components/ui/Skeleton";

// Real ESPN articles about a roster's players plus the daily digest from
// backend team_news_service.py. Ungated public read. A 404 means no news yet.

interface TeamNewsArticle {
  id: string;
  player_name: string;
  headline: string;
  url: string;
  source: string;
  published_at: string;
}

interface TeamNews {
  content: string | null;
  updated_at: string | null;
  articles?: TeamNewsArticle[];
}

export function timeAgo(iso: string, now = Date.now()): string {
  // Backend may send a naive timestamp (SQLite); treat it as UTC.
  const t = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`).getTime();
  const mins = Math.max(0, Math.round((now - t) / 60000));
  if (mins < 60) return `${mins || 1}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

export function PlayerNewsCard({ teamId, limit = 6, digest = true, title = "Player news" }: { teamId: string; limit?: number; digest?: boolean; title?: string }) {
  const [news, setNews] = useState<TeamNews | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    teamNewsApi
      .get(teamId)
      .then((data) => live && setNews(data as TeamNews))
      .catch(() => live && setNews(null))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [teamId]);

  const articles = (news?.articles || []).slice(0, limit);

  return (
    <Card>
      <CardHeader title={title} />
      {loading ? (
        <SkeletonRows rows={3} />
      ) : articles.length === 0 && !(digest && news?.content) ? (
        <p className="text-sm text-ink-400">No news on these players yet. It refreshes every few hours.</p>
      ) : (
        <div className="space-y-4">
          {articles.length > 0 && (
            <ul className="divide-y divide-ink-700">
              {articles.map((a) => (
                <li key={a.id} className="py-2.5 first:pt-0 last:pb-0">
                  <a href={a.url} target="_blank" rel="noopener noreferrer" className="text-sm font-medium leading-snug text-ink-100 hover:text-gold-hi">
                    {a.headline}
                  </a>
                  <p className="mt-0.5 text-xs text-ink-400">
                    <span className="text-ink-300">{a.player_name}</span> · {a.source} ·{" "}
                    <time dateTime={a.published_at}>{timeAgo(a.published_at)}</time>
                  </p>
                </li>
              ))}
            </ul>
          )}
          {digest && news?.content && (
            <details className="group">
              <summary className="flex cursor-pointer items-center gap-1.5 text-label font-semibold uppercase text-ink-400 hover:text-ink-100">
                <Bot className="h-3 w-3" aria-hidden /> Roster digest
              </summary>
              <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-ink-300">{news.content}</p>
            </details>
          )}
        </div>
      )}
    </Card>
  );
}
