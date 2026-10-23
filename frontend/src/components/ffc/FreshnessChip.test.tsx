import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import FreshnessChip from "./FreshnessChip";

describe("FreshnessChip failed prop", () => {
  it("shows a failed chip with Refresh when the page says its reload failed", () => {
    const html = renderToStaticMarkup(<FreshnessChip sources={["sleeper"]} onRefresh={async () => {}} failed />);
    expect(html).toContain("Sync failed");
    expect(html).toContain("Refresh");
    expect(html).not.toContain("just now");
  });

  it("renders nothing before any status loads when nothing failed", () => {
    expect(renderToStaticMarkup(<FreshnessChip sources={["sleeper"]} />)).toBe("");
  });
});
