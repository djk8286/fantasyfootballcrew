import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import AiJobProgress from "./AiJobProgress";

describe("AiJobProgress", () => {
  it("renders a live status with the elapsed time", () => {
    const html = renderToStaticMarkup(<AiJobProgress seconds={12} />);
    expect(html).toContain('role="status"');
    expect(html).toContain("Analyzing your lineup");
    expect(html).toContain("12s");
  });
});
