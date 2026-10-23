"use client";

import type { ReactNode } from "react";
import {
  TIE_BREAK_TIP,
  aliveRowLabel,
  finalistLabel,
  fmt1,
  ordinal,
  outRowLabel,
  seriesText,
  type AliveRow,
  type Finalist,
  type GuillotineState,
  type OutRow,
} from "@/lib/guillotine";
import { Crest } from "./Crest";
import { FfcIcon } from "./icons";
import { Tag } from "./Tag";

const label = "font-ffc-ui text-[11px] font-semibold uppercase tracking-[0.08em] text-ffc-text-muted";
const mono = "font-ffc-mono tabular-nums";

const dash = (color: string, px: number) => ({
  backgroundImage: `repeating-linear-gradient(90deg, ${color} 0 6px, transparent 6px 10px)`,
  height: px,
});

function LiveDot() {
  return <span className="inline-block h-1.5 w-1.5 rounded-full bg-ffc-live" aria-hidden="true" />;
}

function weekHeader(s: GuillotineState): ReactNode {
  if (s.phase === "prekickoff") return <>WK {s.week} · NOT STARTED</>;
  if (s.phase === "live") return <span className="inline-flex items-center gap-1.5"><LiveDot />WK {s.week} LIVE</span>;
  return <>WK {s.week}</>;
}

// ─── Header + tiles ─────────────────────────────────────────

function Pips({ alive, total }: { alive: number; total: number }) {
  return (
    <span className="mt-2 grid w-max grid-cols-6 gap-1 min-[600px]:flex min-[600px]:gap-1" aria-hidden="true">
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={`h-[7px] w-[7px] rounded-[2px] min-[600px]:h-2 min-[600px]:w-2 ${i < alive ? "bg-ffc-live" : "border border-ffc-cut/70"}`}
        />
      ))}
    </span>
  );
}

function Tile({ children, className = "", accent }: { children: ReactNode; className?: string; accent?: "cut" | "finale" }) {
  return (
    <div className={`relative min-h-[76px] overflow-hidden rounded-xl border border-ffc-border bg-ffc-surface p-3.5 min-[600px]:min-h-[88px] min-[600px]:p-4 ${className}`}>
      {accent && <span className={`absolute inset-y-0 left-0 w-[3px] ${accent === "cut" ? "bg-ffc-cut" : "bg-ffc-finale"}`} aria-hidden="true" />}
      {children}
    </div>
  );
}

function Tiles({ s }: { s: GuillotineState }) {
  const third = (() => {
    if (s.phase === "finale") {
      return (
        <Tile accent="finale" className="flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className={`${label} text-ffc-finale`}>FINALE · HEAD-TO-HEAD SERIES</div>
              <div className="mt-1.5 font-ffc-ui text-lg font-semibold text-ffc-text">No more cuts.</div>
              <div className="font-ffc-ui text-[13px] text-ffc-text-muted">They play each other every week; the series decides the title.</div>
            </div>
            <FfcIcon name="trophy" size={20} className="shrink-0 text-ffc-finale" />
          </div>
        </Tile>
      );
    }
    if (s.phase === "prekickoff") {
      return (
        <Tile className="flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className={label}>CUT THIS WEEK</div>
              <div className="mt-1.5 font-ffc-ui text-lg font-semibold text-ffc-text">Cut decided after the last game of Week {s.week}</div>
              <div className="font-ffc-ui text-[13px] text-ffc-text-muted">Nobody is on the block until games start</div>
            </div>
            <FfcIcon name="clock" size={20} className="shrink-0 text-ffc-text-muted" />
          </div>
        </Tile>
      );
    }
    const b = s.block;
    return (
      <Tile accent="cut" className="flex-1">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className={label}>ON THE BLOCK · LOWEST SCORE THIS WEEK</div>
            {b ? (
              <div className="mt-1.5 flex items-center gap-2.5">
                <Crest id={b.team.id} name={b.team.name} avatarUrl={b.team.avatar_url} size={28} />
                <div className="min-w-0">
                  <div className="truncate font-ffc-ui text-lg font-semibold text-ffc-text">{b.team.name}</div>
                  <div className={`${mono} text-[13px] text-ffc-cut-text`}>
                    {fmt1(b.score)} pts{b.behindBy != null && ` · ${fmt1(b.behindBy)} behind ${b.behindName}`}
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-1.5 font-ffc-ui text-[13px] text-ffc-text-muted">No scores yet</div>
            )}
          </div>
          <FfcIcon name="warn" size={20} className="shrink-0 text-ffc-cut-text" />
        </div>
      </Tile>
    );
  })();

  return (
    <div className="mt-6 flex flex-wrap gap-3 min-[600px]:flex-nowrap min-[600px]:gap-4">
      <Tile className="w-[calc(50%-6px)] min-[600px]:w-[200px] min-[600px]:shrink-0">
        <div className="flex items-start justify-between">
          <div className={label}>CURRENT WEEK</div>
          <FfcIcon name="clock" size={20} className="hidden text-ffc-text-muted min-[600px]:block" />
        </div>
        <div className="mt-1 font-ffc-display text-[28px] leading-8 uppercase text-ffc-text min-[600px]:text-4xl">WEEK {s.week}</div>
      </Tile>
      <Tile className="w-[calc(50%-6px)] min-[600px]:w-[264px] min-[600px]:shrink-0">
        <div className="flex items-start justify-between">
          <div className={label}>TEAMS LEFT</div>
          <FfcIcon name="blade" size={20} className="hidden text-ffc-text-muted min-[600px]:block" />
        </div>
        <div className="mt-1 flex flex-wrap items-end gap-x-3" aria-label={`${s.aliveCount} of ${s.totalTeams} teams left`} role="img">
          <span className="font-ffc-display text-[28px] leading-8 text-ffc-text min-[600px]:text-4xl">
            {s.aliveCount}
            <span className="ml-1 text-xl text-ffc-text-muted">/ {s.totalTeams}</span>
          </span>
          <Pips alive={s.aliveCount} total={s.totalTeams} />
        </div>
      </Tile>
      <div className="hidden min-w-0 flex-1 min-[600px]:flex">{third}</div>
    </div>
  );
}

export function GuillotineHeader({ s, leagueName, chip }: { s: GuillotineState; leagueName: string; chip: ReactNode }) {
  const champ = s.phase === "champion";
  return (
    <header className="relative">
      <div
        className="pointer-events-none absolute inset-x-0 top-0 h-[180px]"
        style={{ background: `linear-gradient(to bottom, ${champ || s.phase === "finale" ? "rgba(255,216,115,0.10)" : "rgba(255,59,78,0.10)"}, transparent)` }}
        aria-hidden="true"
      />
      <div className="relative mx-auto max-w-[1280px] px-4 pt-6 min-[600px]:px-10 min-[600px]:pt-8">
        <div className="font-ffc-ui text-xs font-semibold uppercase tracking-[0.08em] text-ffc-text-muted">
          <span className="min-[600px]:hidden">GUILLOTINE · {s.totalTeams} TEAMS</span>
          <span className="hidden min-[600px]:inline">GUILLOTINE · {s.totalTeams}-TEAM LEAGUE</span>
        </div>
        <div className="mt-1 flex flex-col gap-4 min-[600px]:flex-row min-[600px]:items-center min-[600px]:justify-between">
          <h1 className="font-ffc-display text-[28px] leading-8 uppercase text-ffc-text min-[600px]:text-[40px] min-[600px]:leading-[44px]">
            {leagueName}
          </h1>
          <div className="min-w-0">{chip}</div>
        </div>
        {!champ && <Tiles s={s} />}
      </div>
    </header>
  );
}

// ─── Cut band ───────────────────────────────────────────────

function CutBand({ s, as }: { s: GuillotineState; as: "tr" | "li" }) {
  const v = s.cutLine;
  if (!v) return null;
  const neutral = v === "neutral";
  const line =
    v === "live" ? (
      <span className="block h-0.5 bg-ffc-cut" style={{ boxShadow: "var(--ffc-cutline-glow)" }} />
    ) : v === "pending" ? (
      <span className="block h-0.5 bg-ffc-cut" />
    ) : (
      <span className="block" style={dash(neutral ? "var(--ffc-cutline-neutral)" : "rgba(255,59,78,0.7)", 1)} />
    );
  const desk =
    v === "neutral" ? (s.week === 1 && s.noCutsYet ? "CUT LINE" : `CUT LINE · DECIDED AFTER THE LAST GAME OF WEEK ${s.week}`)
    : v === "pending" ? "CUT PENDING · FINAL SCORES"
    : v === "preview" ? "CUT LINE · LOWEST SCORE THIS WEEK IS CUT"
    : "CUT LINE";
  const phone =
    v === "neutral" ? (s.week === 1 && s.noCutsYet ? "CUT LINE" : `CUT AFTER LAST GAME · WK ${s.week}`)
    : v === "preview" ? "LOWEST SCORE IS CUT"
    : desk;
  const pill =
    v === "neutral" ? "border-dashed border-ffc-border-strong text-ffc-text-muted"
    : v === "pending" ? "border-ffc-warn text-ffc-warn"
    : v === "preview" ? "border-dashed border-ffc-cut text-ffc-cut-text"
    : "border-ffc-cut text-ffc-cut-text";
  const icon = v === "neutral" || v === "pending" ? "clock" : "blade";

  const inner = (
    <div className="relative flex h-8 items-center px-2" aria-label={desk}>
      <span className="absolute inset-x-2 top-1/2 -translate-y-1/2">{line}</span>
      <span className={`relative mx-auto inline-flex h-[22px] items-center gap-[5px] rounded-full border bg-ffc-bg px-2.5 font-ffc-mono text-[11px] font-semibold tracking-[0.06em] ${pill}`}>
        <FfcIcon name={icon} size={12} />
        <span className="min-[960px]:hidden" aria-hidden="true">{phone}</span>
        <span className="hidden min-[960px]:inline" aria-hidden="true">{desk}</span>
      </span>
    </div>
  );
  if (as === "tr") {
    return (
      <tr role="separator" aria-label={desk}>
        <td colSpan={6} className="p-0">{inner}</td>
      </tr>
    );
  }
  return <li role="separator" aria-label={desk}>{inner}</li>;
}

function EmptyCuts({ as }: { as: "tr" | "li" }) {
  const body = (
    <div className="flex h-14 flex-col items-center justify-center text-center font-ffc-ui text-[13px] text-ffc-text-muted min-[960px]:h-12">
      <span className="min-[960px]:hidden">No teams cut yet.</span>
      <span className="min-[960px]:hidden">Cut teams drop below this line each week.</span>
      <span className="hidden min-[960px]:inline">No teams cut yet. Cut teams drop below this line after the final game of each week.</span>
    </div>
  );
  return as === "tr" ? <tr><td colSpan={6} className="p-0">{body}</td></tr> : <li>{body}</li>;
}

// ─── Desktop table ──────────────────────────────────────────

const td = "h-14 border-b border-ffc-border/70";

function DeskAliveRow({ r, s }: { r: AliveRow; s: GuillotineState }) {
  const pre = s.phase === "prekickoff";
  return (
    <tr aria-label={aliveRowLabel(r, s.phase)} className={r.onBlock ? "bg-ffc-cut/8" : ""}>
      <td className={`${td} relative w-16 pl-6 ${mono} text-[13px] text-ffc-text-muted`}>
        {r.onBlock && <span className="absolute inset-y-1 left-0 w-[3px] rounded-r bg-ffc-cut" aria-hidden="true" />}
        {r.rank}
      </td>
      <td className={td}>
        <div className="flex min-w-0 items-center gap-3">
          <Crest id={r.team.id} name={r.team.name} avatarUrl={r.team.avatar_url} size={32} />
          <span className="truncate font-ffc-ui text-base font-semibold text-ffc-text">{r.team.name}</span>
        </div>
      </td>
      <td className={`${td} pr-4 text-right ${mono} text-[15px] font-semibold text-ffc-text`}>{pre || r.score == null ? "—" : fmt1(r.score)}</td>
      <td className={`${td} hidden pr-4 text-right ${mono} text-[13px] text-ffc-text-muted min-[1120px]:table-cell`}>{r.projected == null ? "—" : fmt1(r.projected)}</td>
      <td className={`${td} pr-6 text-right ${mono} text-[13px] text-ffc-text-muted`}>{fmt1(r.team.points_for)}</td>
      <td className={`${td} w-[184px] pr-6`}>
        {pre ? (
          <span className="font-ffc-ui text-[13px] text-ffc-text-muted">Not started</span>
        ) : r.onBlock ? (
          <Tag kind="block">ON THE BLOCK</Tag>
        ) : (
          <span className={`inline-flex items-center gap-1.5 ${mono} text-[13px] text-ffc-text-muted`}>
            <FfcIcon name="up" size={14} className="text-ffc-live" />
            {fmt1(r.clearBy ?? 0)} clear
          </span>
        )}
      </td>
    </tr>
  );
}

function DeskOutRow({ r }: { r: OutRow }) {
  return (
    <tr aria-label={outRowLabel(r)}>
      <td className={`${td} pl-6 ${mono} text-[13px] text-ffc-text-faded`}>{ordinal(r.place)}</td>
      <td className={td}>
        <div className="flex min-w-0 items-center gap-3">
          <Crest id={r.team.id} name={r.team.name} avatarUrl={r.team.avatar_url} size={32} faded />
          <span className="truncate font-ffc-ui text-base font-semibold text-ffc-text-faded">{r.team.name}</span>
        </div>
      </td>
      <td className={`${td} pr-4 text-right ${mono} text-[15px] text-ffc-text-faded`}>—</td>
      <td className={`${td} hidden pr-4 text-right ${mono} text-[13px] text-ffc-text-faded min-[1120px]:table-cell`}>—</td>
      <td className={`${td} pr-6 text-right ${mono} text-[13px] text-ffc-text-faded`}>{fmt1(r.team.points_for)}</td>
      <td className={`${td} pr-6`}>
        <Tag kind="cut" tip={TIE_BREAK_TIP}>CUT · WK {r.cutWeek}</Tag>
      </td>
    </tr>
  );
}

function DeskTable({ s, caption, firstCol = "RANK", weekCol }: { s: GuillotineState; caption: string; firstCol?: string; weekCol: ReactNode }) {
  const th = `${label} h-10 bg-ffc-raised px-0 text-left font-semibold`;
  return (
    <table className="hidden w-full table-fixed border-separate border-spacing-0 rounded-xl border border-ffc-border bg-ffc-surface min-[960px]:table">
      <caption className="sr-only">{caption}</caption>
      <colgroup>
        <col className="w-16" />
        <col />
        <col className="w-[130px]" />
        <col className="hidden w-[110px] min-[1120px]:table-column" />
        <col className="w-[130px]" />
        <col className="w-[184px]" />
      </colgroup>
      <thead>
        <tr>
          <th scope="col" className={`${th} rounded-tl-xl pl-6`}>{firstCol}</th>
          <th scope="col" className={`${th} pl-11`}>TEAM</th>
          <th scope="col" className={`${th} pr-4 text-right`}>{weekCol}</th>
          <th scope="col" className={`${th} hidden pr-4 text-right min-[1120px]:table-cell`}>PROJ</th>
          <th scope="col" className={`${th} pr-6 text-right`}>SEASON</th>
          <th scope="col" className={`${th} rounded-tr-xl`}>STATUS</th>
        </tr>
      </thead>
      <tbody>
        {s.alive.map((r) => <DeskAliveRow key={r.team.id} r={r} s={s} />)}
        <CutBand s={s} as="tr" />
        {s.noCutsYet && s.alive.length > 0 && <EmptyCuts as="tr" />}
        {s.out.map((r) => <DeskOutRow key={r.team.id} r={r} />)}
      </tbody>
    </table>
  );
}

// ─── Phone list ─────────────────────────────────────────────

function PhoneAliveRow({ r, s }: { r: AliveRow; s: GuillotineState }) {
  const pre = s.phase === "prekickoff";
  const big = pre ? r.projected : r.score;
  return (
    <li aria-label={aliveRowLabel(r, s.phase)} className={`relative flex h-16 items-center gap-2.5 border-b border-ffc-border/70 px-3.5 ${r.onBlock ? "bg-ffc-cut/8" : ""}`}>
      {r.onBlock && <span className="absolute inset-y-1 left-0 w-[3px] rounded-r bg-ffc-cut" aria-hidden="true" />}
      <span className={`w-5 shrink-0 ${mono} text-sm text-ffc-text-muted`}>{r.rank}</span>
      <Crest id={r.team.id} name={r.team.name} avatarUrl={r.team.avatar_url} size={28} />
      <div className="min-w-0 flex-1">
        <div className="truncate font-ffc-ui text-[15px] font-semibold leading-5 text-ffc-text">{r.team.name}</div>
        {r.onBlock ? (
          <div className="mt-0.5"><Tag kind="block" compact>ON THE BLOCK</Tag></div>
        ) : (
          <div className={`${mono} text-xs text-ffc-text-muted`}>Season {fmt1(r.team.points_for)}</div>
        )}
      </div>
      <div className="shrink-0 text-right">
        <div className={`${mono} text-base font-semibold text-ffc-text`}>{big == null ? "—" : fmt1(big)}</div>
        <div className={`${mono} text-[11px] text-ffc-text-muted`}>
          {pre ? "proj · not started" : r.projected == null ? "" : `proj ${fmt1(r.projected)}`}
        </div>
      </div>
    </li>
  );
}

function PhoneOutRow({ r }: { r: OutRow }) {
  return (
    <li aria-label={outRowLabel(r)} className="flex h-16 items-center gap-2.5 border-b border-ffc-border/70 px-3.5 last:border-b-0">
      <span className={`w-5 shrink-0 ${mono} text-sm text-ffc-text-faded`}>{r.place}</span>
      <Crest id={r.team.id} name={r.team.name} avatarUrl={r.team.avatar_url} size={28} faded />
      <div className="min-w-0 flex-1">
        <div className="truncate font-ffc-ui text-[15px] font-semibold leading-5 text-ffc-text-faded">{r.team.name}</div>
        <div className="mt-0.5"><Tag kind="cut" tip={TIE_BREAK_TIP} compact align="start">CUT · WK {r.cutWeek}</Tag></div>
      </div>
      <div className="shrink-0 text-right">
        <div className={`${mono} text-base text-ffc-text-faded`}>{fmt1(r.team.points_for)}</div>
        <div className={`${mono} text-[11px] text-ffc-text-faded`}>{ordinal(r.place)}</div>
      </div>
    </li>
  );
}

function PhoneList({ s, caption, rightCol }: { s: GuillotineState; caption: string; rightCol: ReactNode }) {
  return (
    <div className="rounded-xl border border-ffc-border bg-ffc-surface min-[960px]:hidden">
      <div className={`${label} flex h-9 items-center justify-between rounded-t-xl bg-ffc-raised px-3.5`} aria-hidden="true">
        <span>TEAM</span>
        <span>{rightCol}</span>
      </div>
      <ol aria-label={caption}>
        {s.alive.map((r) => <PhoneAliveRow key={r.team.id} r={r} s={s} />)}
        <CutBand s={s} as="li" />
        {s.noCutsYet && s.alive.length > 0 && <EmptyCuts as="li" />}
        {s.out.map((r) => <PhoneOutRow key={r.team.id} r={r} />)}
      </ol>
    </div>
  );
}

// ─── Finale card ────────────────────────────────────────────

function SeriesLine({ f, small = false }: { f: Finalist; small?: boolean }) {
  return (
    <div className={`${mono} ${small ? "text-xs" : "text-[13px]"} leading-4 text-ffc-text-muted`}>
      <span className="font-semibold text-ffc-text">{seriesText(f.series)}</span> series ·{" "}
      <span className="font-semibold text-ffc-text">{fmt1(f.series.points)}</span> finale pts
    </div>
  );
}

function FinaleCard({ s }: { s: GuillotineState }) {
  const fin = s.finale!;
  const live = s.phase === "finale" && fin.finalists.some((f) => f.score != null);
  const tied = fin.tiedLabel && fin.tiedTip ? <Tag kind="tied" tip={fin.tiedTip}>{fin.tiedLabel}</Tag> : null;
  const tiedPhone = fin.tiedLabel && fin.tiedTip ? <Tag kind="tied" tip={fin.tiedTip} compact align="end">{fin.tiedLabel}</Tag> : null;
  const weekRight = (
    <span className={`${label} inline-flex items-center gap-1.5`}>
      {live && <LiveDot />}
      <span className="hidden min-[960px]:inline">HEAD-TO-HEAD · </span>WK {fin.week}{live ? " LIVE" : ""}
    </span>
  );

  const desk = (f: Finalist, side: "left" | "right") => (
    <li aria-label={finalistLabel(f, s.phase)} className={`flex min-w-0 flex-1 items-center gap-4 ${side === "right" ? "flex-row-reverse text-right" : ""}`}>
      <Crest id={f.team.id} name={f.team.name} avatarUrl={f.team.avatar_url} size={56} />
      <div className="min-w-0 flex-1">
        <div className="truncate font-ffc-ui text-[22px] font-semibold leading-7 text-ffc-text">{f.team.name}</div>
        <div className="font-ffc-ui text-xs text-ffc-text-muted">Season {fmt1(f.team.points_for)}</div>
        <div className="mt-1"><SeriesLine f={f} /></div>
        {f.leading && <div className="mt-2.5"><Tag kind="leading">LEADING</Tag></div>}
      </div>
      <div className="shrink-0">
        <div className="font-ffc-display text-[44px] leading-[48px] text-ffc-text">{f.score == null ? "—" : fmt1(f.score)}</div>
        <div className={`${mono} text-[11px] text-ffc-text-muted`}>WK {fin.week}{f.projected != null && ` · proj ${fmt1(f.projected)}`}</div>
      </div>
    </li>
  );

  const phone = (f: Finalist) => (
    <li aria-label={finalistLabel(f, s.phase)} className="flex min-h-[76px] items-center gap-3 px-3.5">
      <Crest id={f.team.id} name={f.team.name} avatarUrl={f.team.avatar_url} size={36} />
      <div className="min-w-0 flex-1 pr-3">
        <div className="truncate font-ffc-ui text-base font-semibold text-ffc-text">{f.team.name}</div>
        <SeriesLine f={f} small />
        {f.leading && <div className="mt-1"><Tag kind="leading" compact>LEADING</Tag></div>}
      </div>
      <div className="shrink-0 text-right">
        <div className="font-ffc-display text-4xl leading-9 text-ffc-text">{f.score == null ? "—" : fmt1(f.score)}</div>
        {f.projected != null && <div className={`${mono} text-[11px] text-ffc-text-muted`}>proj {fmt1(f.projected)}</div>}
      </div>
    </li>
  );

  const vs = (
    <span className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-ffc-finale/50 bg-ffc-bg font-ffc-display text-sm text-ffc-finale min-[960px]:h-10 min-[960px]:w-10 min-[960px]:text-base" aria-hidden="true">
      VS
    </span>
  );
  const [a, b] = fin.finalists;

  return (
    <section aria-label={`Finale series, week ${fin.week}`} className="rounded-xl border border-[var(--ffc-finale-card-border)] bg-ffc-surface" style={{ backgroundImage: "linear-gradient(var(--ffc-finale-card-bg), var(--ffc-finale-card-bg))" }}>
      <div className="flex h-11 items-center justify-between px-3.5 min-[960px]:px-6">
        <span className={`${label} inline-flex items-center gap-1.5 text-ffc-finale`}>
          <FfcIcon name="trophy" size={14} />FINALE · WEEK {fin.week}
        </span>
        <span className={"min-[960px]:hidden"}>{tiedPhone ?? weekRight}</span>
        <span className="hidden min-[960px]:inline">{weekRight}</span>
      </div>
      {/* desktop */}
      <div className="hidden px-6 pb-4 min-[960px]:block">
        <ul className="flex items-center gap-6">
          {desk(a, "left")}
          <li className="flex shrink-0 flex-col items-center gap-3" aria-hidden={!tied}>
            {vs}
            {tied}
          </li>
          {desk(b, "right")}
        </ul>
        <p className={`mt-4 text-center ${mono} text-xs text-ffc-text-muted`}>{fin.leadLine}</p>
      </div>
      {/* phone */}
      <div className="pb-3 min-[960px]:hidden">
        <ul>
          {phone(a)}
          <li className="relative my-1 flex h-8 items-center justify-center" aria-hidden="true">
            <span className="absolute inset-x-3.5 top-1/2 h-px bg-ffc-border" />
            <span className="relative">{vs}</span>
          </li>
          {phone(b)}
        </ul>
        <p className={`mt-2 px-3.5 text-center ${mono} text-[11px] text-ffc-text-muted`}>{fin.leadLineShort}</p>
      </div>
    </section>
  );
}

// ─── Champion ───────────────────────────────────────────────

function ChampionBanner({ s }: { s: GuillotineState }) {
  // The backend sends the champion first (guillotine_placement.py).
  const [c] = s.finale!.finalists;
  const finaleWeeks = s.finale!.weeks;
  const lastWeek = finaleWeeks[finaleWeeks.length - 1] ?? s.week;
  const wonOutright = c.series.wins > c.series.losses;
  const range = finaleWeeks.length ? `${finaleWeeks[0]}–${lastWeek}` : `${lastWeek}`;
  const stats: [string, string][] = [
    ["SERIES", seriesText(c.series)],
    ["FINALE PTS", fmt1(c.series.points)],
    ["SEASON PTS", fmt1(c.team.points_for)],
  ];
  return (
    <section
      aria-label="Champion, season final"
      className="relative overflow-hidden rounded-2xl bg-ffc-surface"
      style={{
        backgroundImage: "linear-gradient(var(--ffc-champion-banner-bg), var(--ffc-champion-banner-bg))",
        border: "1.5px solid var(--ffc-champion-banner-border)",
      }}
    >
      <span className="ffc-shine" aria-hidden="true" />
      <div className="relative p-3.5 min-[960px]:p-6">
        <div className="flex items-center gap-6">
          <span className="hidden h-20 w-20 shrink-0 items-center justify-center rounded-full min-[960px]:flex" style={{ background: "var(--ffc-medallion-bg)", border: "1.5px solid var(--ffc-medallion-border)" }} aria-hidden="true">
            <FfcIcon name="trophy" size={40} className="text-ffc-finale" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="inline-flex items-center gap-1.5 font-ffc-ui text-xs font-semibold tracking-[0.08em] text-ffc-finale">
              <FfcIcon name="trophy" size={18} className={"min-[960px]:hidden"} />
              CHAMPION · SEASON FINAL<span className="hidden min-[960px]:inline"> · WEEK {lastWeek}</span>
            </div>
            <div className="mt-2 flex min-w-0 items-center gap-3">
              <span className="min-[960px]:hidden"><Crest id={c.team.id} name={c.team.name} avatarUrl={c.team.avatar_url} size={44} /></span>
              <span className="hidden min-[960px]:inline-flex"><Crest id={c.team.id} name={c.team.name} avatarUrl={c.team.avatar_url} size={48} /></span>
              <div className="min-w-0">
                <h2 className="truncate font-ffc-display text-[28px] uppercase leading-8 tracking-[0.01em] text-ffc-text min-[960px]:text-[44px] min-[960px]:leading-[48px]">
                  <span className="sr-only">{c.team.name}, champion</span>
                  <span aria-hidden="true">{c.team.name}</span>
                </h2>
                <div className="font-ffc-ui text-xs text-ffc-text-muted min-[960px]:text-sm">
                  <span className="min-[960px]:hidden">1st of {s.totalTeams}</span>
                  <span className="hidden min-[960px]:inline">
                    {wonOutright ? `Won the finale series ${seriesText(c.series)}` : `Series ${seriesText(c.series)}, won on the tie-break`}
                  </span>
                </div>
              </div>
            </div>
          </div>
          <dl className="hidden shrink-0 min-[960px]:flex">
            {stats.map(([k, v], i) => (
              <div key={k} className={`w-[150px] pl-6 text-right ${i ? "border-l" : ""}`} style={{ borderColor: "rgba(255,216,115,0.25)" }}>
                <dt className={label}>{k}</dt>
                <dd className="font-ffc-display text-4xl leading-10 text-ffc-text">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
        <dl className="mt-3 grid grid-cols-3 border-t pt-3 min-[960px]:hidden" style={{ borderColor: "rgba(255,216,115,0.25)" }}>
          {stats.map(([k, v]) => (
            <div key={k} className="text-center">
              <dt className={label}>{k}</dt>
              <dd className="font-ffc-display text-[26px] leading-[30px] text-ffc-text">{v}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-3 flex items-center justify-between border-t pt-3 font-ffc-ui text-xs text-ffc-text-muted min-[960px]:mt-5 min-[960px]:text-[13px]" style={{ borderColor: "rgba(255,216,115,0.25)" }}>
          <span className="w-full text-center min-[960px]:hidden">Season complete · finale weeks {range}</span>
          <span className="hidden min-[960px]:inline">Season complete · 1st of {s.totalTeams} · finale series weeks {range}</span>
          <a href="#final-standings" className="hidden font-semibold text-ffc-finale hover:underline min-[960px]:inline">Final standings</a>
        </div>
      </div>
    </section>
  );
}

function RunnerUp({ s }: { s: GuillotineState }) {
  const r = s.finale!.finalists[1];
  return (
    <section aria-label={`Runner-up, ${r.team.name}, 2nd, ${finalistLabel(r, s.phase)}`} className="mt-3 flex h-16 items-center gap-2.5 rounded-xl border border-ffc-border bg-ffc-surface px-3.5 min-[960px]:mt-4 min-[960px]:h-[72px] min-[960px]:gap-3 min-[960px]:px-6">
      <span className={`w-5 shrink-0 ${mono} text-sm text-ffc-text-muted min-[960px]:w-10 min-[960px]:text-[15px]`}>
        <span className="min-[960px]:hidden">2</span><span className="hidden min-[960px]:inline">2nd</span>
      </span>
      <span className="min-[960px]:hidden"><Crest id={r.team.id} name={r.team.name} avatarUrl={r.team.avatar_url} size={28} /></span>
      <span className="hidden min-[960px]:inline-flex"><Crest id={r.team.id} name={r.team.name} avatarUrl={r.team.avatar_url} size={40} /></span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-3">
          <span className="truncate font-ffc-ui text-[15px] font-semibold text-ffc-text-muted min-[960px]:text-lg">{r.team.name}</span>
          <span className="hidden min-[960px]:inline-flex"><Tag kind="runnerup">RUNNER-UP</Tag></span>
        </div>
        <span className="mt-0.5 inline-flex min-[960px]:hidden"><Tag kind="runnerup" compact>RUNNER-UP</Tag></span>
      </div>
      <div className={`shrink-0 text-right ${mono} text-ffc-text-muted`}>
        <span className="hidden text-[15px] min-[960px]:inline">
          {seriesText(r.series)} series · {fmt1(r.series.points)} finale pts · {fmt1(r.team.points_for)} season
        </span>
        <span className="min-[960px]:hidden">
          <span className="block text-base font-semibold">{seriesText(r.series)}</span>
          <span className="block text-[11px]">{fmt1(r.series.points)} finale pts</span>
        </span>
      </div>
    </section>
  );
}

function Eliminated({ s }: { s: GuillotineState }) {
  if (!s.out.length) return null;
  const hdr = `ELIMINATED · ${s.out.length} TEAMS`;
  return (
    <div className="mt-6" id="final-standings">
      <h2 className={`${label} mb-3`}>{hdr}</h2>
      <DeskTable s={s} caption="Eliminated teams" firstCol="PLACE" weekCol={<>WK {s.week}</>} />
      <PhoneList s={s} caption="Eliminated teams" rightCol="SEASON" />
    </div>
  );
}

// ─── Page body ──────────────────────────────────────────────

function Footer({ desk, phone }: { desk: string; phone: string[] }) {
  return (
    <div className="mt-7 font-ffc-ui text-[13px] leading-5 text-ffc-text-muted">
      <p className="hidden min-[960px]:block">{desk}</p>
      <div className={"min-[960px]:hidden"}>{phone.map((l) => <p key={l}>{l}</p>)}</div>
    </div>
  );
}

export function GuillotineBody({ s }: { s: GuillotineState }) {
  if (s.phase === "champion" && s.finale) {
    return (
      <div className="mx-auto max-w-[1280px] px-4 pb-10 pt-6 min-[600px]:px-10">
        <ChampionBanner s={s} />
        <RunnerUp s={s} />
        <Eliminated s={s} />
        <Footer
          desk="Season final. The finale series decides 1st and 2nd. A level series goes to finale points, then season points. Everyone else places by when they were cut, latest cut highest."
          phone={["Season final. Places come from the final standings."]}
        />
      </div>
    );
  }
  if (s.phase === "finale" && s.finale) {
    return (
      <div className="mx-auto max-w-[1280px] px-4 pb-10 pt-6 min-[600px]:px-10">
        <FinaleCard s={s} />
        <Eliminated s={s} />
        <Footer
          desk="Cuts stop at 2 teams. The finalists play each other every week until the season ends. The better series record wins the title. A level series goes to finale points, then season points."
          phone={["Cuts stop at 2 teams. The finalists play every week.", "Series record decides the title, then finale points, then season points."]}
        />
      </div>
    );
  }
  const caption = `Guillotine standings, week ${s.week}`;
  const pre = s.phase === "prekickoff";
  return (
    <div className="mx-auto max-w-[1280px] px-4 pb-10 pt-6 min-[600px]:px-10">
      <DeskTable s={s} caption={caption} weekCol={weekHeader(s)} />
      <PhoneList s={s} caption={caption} rightCol={weekHeader(s)} />
      {pre ? (
        <Footer
          desk="Sorted by projection until games start. One cut per week, made when the week rolls over after its last game."
          phone={[`Cut decided after the last game of Week ${s.week}.`, "Nobody is on the block until games start."]}
        />
      ) : (
        <Footer
          desk="Lowest score each week is cut after the final game of the week. Scores update live; tags and the line never rely on color alone."
          phone={["Lowest score each week is cut after the final game of the week."]}
        />
      )}
    </div>
  );
}
