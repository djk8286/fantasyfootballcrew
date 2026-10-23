import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { deriveGuillotine, TIE_BREAK_TIP, type GGame, type GTeam } from "@/lib/guillotine";
import { GuillotineBody, GuillotineHeader } from "./GuillotineSkin";
import { Tag } from "./Tag";

const team = (id: string, season: number, cut: number | null = null): GTeam => ({
  id, name: id.toUpperCase(), eliminated_week: cut, created_at: "2026-08-01T00:00:00Z", points_for: season,
});
const live: GGame = { status_state: "in", completed: false };
const final: GGame = { status_state: "post", completed: true };
const render = (s: ReturnType<typeof deriveGuillotine>, finaleWeeks: number[] = []) =>
  renderToStaticMarkup(
    <>
      <GuillotineHeader s={s} leagueName="Test League" chip={null} />
      <GuillotineBody s={s} finaleWeeks={finaleWeeks} />
    </>,
  );

describe("Tag tooltip", () => {
  it("is focusable and points aria-describedby at its tooltip", () => {
    const html = renderToStaticMarkup(<Tag kind="cut" tip={TIE_BREAK_TIP}>CUT · WK 3</Tag>);
    const describedBy = html.match(/aria-describedby="([^"]+)"/)?.[1];
    expect(describedBy).toBeTruthy();
    expect(html).toContain(`id="${describedBy}"`);
    expect(html).toMatch(/role="tooltip"/);
    expect(html).toMatch(/tabindex="0"/);
    expect(html).toContain("Lowest score · tie-break: season points");
  });

  it("renders a plain label without a tooltip", () => {
    const html = renderToStaticMarkup(<Tag kind="block">ON THE BLOCK</Tag>);
    expect(html).not.toContain("tooltip");
    expect(html).not.toContain("tabindex");
  });
});

describe("GuillotineSkin", () => {
  const teams = [team("a", 900), team("b", 850), team("c", 800), team("d", 700, 2), team("e", 400, 1)];
  const scores = [
    { team_id: "a", total_score: 90, projected_score: null },
    { team_id: "b", total_score: 80, projected_score: null },
    { team_id: "c", total_score: 70, projected_score: null },
  ];

  it("live week shows the block, teams left, and faded cut rows without opacity", () => {
    const html = render(deriveGuillotine({ week: 3, teams, scores, games: [live] }));
    expect(html).toContain("TEAMS LEFT");
    expect(html).toContain("ON THE BLOCK");
    expect(html).toContain("CUT · WK 2");
    expect(html).toContain("text-ffc-text-faded");
    expect(html).not.toMatch(/<tr[^>]*opacity/);
  });

  it("champion shows the banner and runner-up and drops the tiles", () => {
    const champTeams = [team("cd", 2126.4), team("ww", 2151.7), team("bb", 1010.5, 10), team("tt", 902.6, 9)];
    const wk = (cd: number, ww: number) => [{ home_team_id: "ww", home_score: ww, away_team_id: "cd", away_score: cd }];
    const weeks = [wk(130, 120), wk(120, 130), wk(125, 110), wk(140, 100), wk(90, 110), wk(120, 119.9), wk(117.7, 112)];
    const s = deriveGuillotine({ week: 17, teams: champTeams, games: [final], scores: [], finaleWeeks: weeks, seasonOver: true });
    const html = render(s, [11, 12, 13, 14, 15, 16, 17]);
    expect(html).toContain("CHAMPION · SEASON FINAL");
    expect(html).toContain("RUNNER-UP");
    expect(html).not.toContain("TEAMS LEFT");
    expect(html.indexOf("CD")).toBeLessThan(html.indexOf("RUNNER-UP"));
  });
});
