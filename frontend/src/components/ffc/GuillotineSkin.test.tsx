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
const render = (s: ReturnType<typeof deriveGuillotine>) =>
  renderToStaticMarkup(
    <>
      <GuillotineHeader s={s} leagueName="Test League" chip={null} />
      <GuillotineBody s={s} />
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
    const s = deriveGuillotine({
      week: 18, teams: champTeams, games: [final], scores: [],
      summary: {
        phase: "final", champion_team_id: "cd", runner_up_team_id: "ww",
        finalists: [
          { team_id: "cd", wins: 5, losses: 2, ties: 0, points: 842.7 },
          { team_id: "ww", wins: 2, losses: 5, ties: 0, points: 801.9 },
        ],
        finale_weeks: [11, 12, 13, 14, 15, 16, 17],
        places: { cd: 1, ww: 2, bb: 3, tt: 4 },
      },
    });
    const html = render(s);
    expect(html).toContain("CHAMPION · SEASON FINAL");
    expect(html).toContain("RUNNER-UP");
    expect(html).not.toContain("TEAMS LEFT");
    expect(html.indexOf("CD")).toBeLessThan(html.indexOf("RUNNER-UP"));
    expect(html).toContain("finale series weeks 11–17");
    expect(html).toContain("then season points");
  });

  it("a week-18 last cut with no finale games reads won on season points", () => {
    const teams = [team("cd", 2151.7), team("ww", 2126.4), team("bb", 1010.5, 18), team("tt", 902.6, 9)];
    const s = deriveGuillotine({
      week: 18, teams, games: [final], scores: [],
      summary: {
        phase: "final", champion_team_id: "cd", runner_up_team_id: "ww",
        finalists: [
          { team_id: "cd", wins: 0, losses: 0, ties: 0, points: 0 },
          { team_id: "ww", wins: 0, losses: 0, ties: 0, points: 0 },
        ],
        finale_weeks: [],
        places: { cd: 1, ww: 2, bb: 3, tt: 4 },
      },
    });
    const html = render(s);
    expect(html).toContain("CHAMPION · SEASON FINAL");
    expect(html).toContain("Won on season points");
    expect(html).not.toContain("tie-break</span>");
    expect(html).not.toMatch(/Series 0.0/);
    expect(html).not.toContain(">SERIES<");
    expect(html).not.toContain(">FINALE PTS<");
    expect(html).not.toContain("finale series weeks");
    expect(html).not.toContain("finale weeks 18");
    expect(html).toContain(">SEASON PTS<");
    expect(html).toContain("2126.4 season pts");
    expect(html).toContain("Runner-up, WW, 2nd, WW, 2126.4 season points");
  });

  it("a series tied after real finale games still says won on the tie-break", () => {
    const teams = [team("cd", 2151.7), team("ww", 2126.4), team("bb", 1010.5, 10), team("tt", 902.6, 9)];
    const s = deriveGuillotine({
      week: 18, teams, games: [final], scores: [],
      summary: {
        phase: "final", champion_team_id: "cd", runner_up_team_id: "ww",
        finalists: [
          { team_id: "cd", wins: 4, losses: 4, ties: 0, points: 900 },
          { team_id: "ww", wins: 4, losses: 4, ties: 0, points: 880 },
        ],
        finale_weeks: [11, 12, 13, 14, 15, 16, 17, 18],
        places: { cd: 1, ww: 2, bb: 3, tt: 4 },
      },
    });
    const html = render(s);
    expect(html).toContain("Series 4–4, won on the tie-break");
    expect(html).toContain(">SERIES<");
    expect(html).not.toContain("Won on season points");
  });
});
