import { describe, expect, it } from "vitest";
import { errorStatus, leagueGate, loadProblem } from "./access-problem";

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

describe("leagueGate", () => {
  const err = (status: number, detail: unknown) => Object.assign(new Error("x"), { status, detail });
  it("guest on a private league: log in, with the league's name", () => {
    expect(leagueGate(err(401, { message: "Not authenticated", league: { id: "l", name: "QA 4", visibility: "private" } }))).toEqual({
      kind: "login",
      name: "QA 4",
      invited: false,
    });
  });
  it("logged-in non-member: private, and notices a pending invite", () => {
    expect(leagueGate(err(403, { league: { name: "QA 4", viewer_join_status: "invited" } }))).toEqual({ kind: "private", name: "QA 4", invited: true });
  });
  it("copes with a plain-string detail", () => {
    expect(leagueGate(err(401, "Not authenticated"))).toEqual({ kind: "login", name: null, invited: false });
  });
  it("anything else is not a gate", () => {
    expect(leagueGate(err(404, "League not found"))).toBeNull();
    expect(leagueGate(new Error("network"))).toBeNull();
    expect(leagueGate(null)).toBeNull();
  });
});
