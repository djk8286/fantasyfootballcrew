import { describe, expect, it } from "vitest";
import { errorStatus, loadProblem } from "./access-problem";

describe("loadProblem", () => {
  it("asks guests to log in, per page", () => {
    expect(loadProblem(401, "lineup")).toEqual({ kind: "login", text: "to see this lineup." });
    expect(loadProblem(401, "team")).toEqual({ kind: "login", text: "to see this team." });
    expect(loadProblem(401, "league")).toEqual({ kind: "login", text: "to see this league." });
  });
  it("explains private leagues", () => {
    expect(loadProblem(403, "lineup").text).toBe("This league is private. Only its members can see lineups.");
    expect(loadProblem(403, "team").text).toBe("This league is private. Only its members can see it.");
  });
  it("falls back to retry text", () => {
    expect(loadProblem(null, "team")).toEqual({ kind: "message", text: "Couldn't load this team. Try again in a moment." });
    expect(loadProblem(500, "league").kind).toBe("message");
    expect(loadProblem(404, "league").text).toBe("We couldn't find this league.");
  });
});

describe("errorStatus", () => {
  it("reads numeric status only", () => {
    expect(errorStatus({ status: 401 })).toBe(401);
    expect(errorStatus(new Error("x"))).toBeNull();
    expect(errorStatus(null)).toBeNull();
  });
});
