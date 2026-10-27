import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import StatusBoard from "./StatusBoard";
import StatusReport from "./StatusReport";
import type { StatusReport as StatusReportModel } from "@/lib/status-page";

const report: StatusReportModel = {
  level: "degraded",
  headline: "Some systems need attention",
  summary: "The API is responding, but NFL data may be behind.",
  components: [
    { id: "api", name: "API", level: "operational", label: "Operational", detail: "Responding" },
    { id: "sleeper", name: "Sleeper stats", level: "degraded", label: "Degraded", detail: "Last sync 14m ago" },
    { id: "espn", name: "ESPN scores", level: "operational", label: "Operational", detail: "Last sync 1m ago" },
  ],
};

describe("status page", () => {
  it("renders the public checking state before any request", () => {
    const html = renderToStaticMarkup(<StatusBoard />);
    expect(html).toContain("System status");
    expect(html).toContain("Checking the API and the NFL sync.");
    expect(html).not.toContain("All systems operational");
    expect(html).not.toContain("/login");
  });

  it("shows overall status, API health, and each sync with a text label", () => {
    const html = renderToStaticMarkup(
      <StatusReport report={report} checkedLabel="Updated just now" onRefresh={() => {}} refreshing={false} />,
    );
    expect(html).toContain("Some systems need attention");
    expect(html).toContain("NFL data may be behind");
    expect(html).toContain("Sleeper stats");
    expect(html).toContain("Last sync 14m ago");
    expect(html).toContain("ESPN scores");
    expect(html).toContain(">Degraded<");
    expect(html).toContain(">Operational<");
    expect(html).toContain("Updated just now");
    expect(html).toContain("Refresh");
    expect(html).toContain('data-level="degraded"');
    expect(html).toContain('data-component="api"');
  });
});
