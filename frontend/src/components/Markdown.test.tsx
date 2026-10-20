import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import Markdown, { parseBlocks, safeHref } from "./Markdown";

const html = (t: string) => renderToStaticMarkup(<Markdown text={t} />);

describe("Markdown (AI output)", () => {
  it("renders headings, bold, lists and tables instead of raw syntax", () => {
    const out = html("## Trade Summary\n**Team A gives:** Bijan\n\n- one\n- two\n\n| Team | Grade |\n|---|---|\n| A | B+ |");
    expect(out).toContain("<h3");
    expect(out).toContain("<strong");
    expect(out).toContain("<li>one</li>");
    expect(out).toContain("<table");
    expect(out).toContain("<td");
    expect(out).not.toMatch(/##|\*\*|\|---/);
  });

  it("links only http(s) and opens them safely", () => {
    const out = html("See ([nfl.com](https://www.nfl.com/news?utm_source=openai)) and [x](javascript:alert(1))");
    expect(out).toContain('href="https://www.nfl.com/news?utm_source=openai"');
    expect(out).toContain('rel="noopener noreferrer nofollow"');
    expect(out).not.toContain("javascript:");
    expect(safeHref("data:text/html,hi")).toBeNull();
  });

  it("never renders raw HTML from the model", () => {
    const out = html('<img src=x onerror="alert(1)"> **hi** <script>alert(1)</script>');
    expect(out).not.toContain("<img");
    expect(out).not.toContain("<script");
    expect(out).toContain("&lt;script&gt;");
  });

  it("keeps plain text as paragraphs with line breaks", () => {
    expect(parseBlocks("START: Josh Allen\nReason: matchup")).toEqual([{ kind: "para", lines: ["START: Josh Allen", "Reason: matchup"] }]);
  });
});

describe("Markdown inline edge cases", () => {
  it("doesn't italicize snake_case identifiers", () => {
    expect(html("use player_id and team_id")).not.toContain("<em>");
    expect(html("an _emphasized_ word")).toContain("<em>emphasized</em>");
  });
});
