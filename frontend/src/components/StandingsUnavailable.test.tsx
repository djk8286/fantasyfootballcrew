import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import StandingsUnavailable from "./StandingsUnavailable";

describe("StandingsUnavailable", () => {
  const html = renderToStaticMarkup(
    <StandingsUnavailable leagueId="L1" leagueName="Sunday Crew" message="The server had a problem." onRetry={() => {}} />,
  );

  it("keeps the page header and shows the error inline below it", () => {
    const header = html.indexOf("<h1");
    const alert = html.indexOf('role="alert"');
    expect(header).toBeGreaterThan(-1);
    expect(html).toContain(">Standings</h1>");
    expect(html).toContain("Sunday Crew");
    expect(alert).toBeGreaterThan(header);
    expect(html).toContain("Couldn&#x27;t load standings");
    expect(html).toContain("The server had a problem.");
  });

  it("offers a retry and a way back, and isn't a centered full-page takeover", () => {
    expect(html).toContain("Try again");
    expect(html).toContain('href="/leagues/L1"');
    expect(html).not.toMatch(/min-h-screen[^"]*justify-center/);
  });

  it("works before the league name is known", () => {
    const bare = renderToStaticMarkup(<StandingsUnavailable leagueId="L1" message="We couldn't find this league." />);
    expect(bare).toContain(">Standings</h1>");
    expect(bare).toContain('role="alert"');
    expect(bare).not.toContain("Try again");
  });
});
