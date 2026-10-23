import { describe, expect, it } from "vitest";
import { errorStatus, leagueGate, loadProblem, loginHref, safeNext } from "./access-problem";

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

describe("safeNext", () => {
  it("keeps a same-site path with its query and hash", () => {
    expect(safeNext("/league/abc/trades?week=7&team=x#offer")).toBe("/league/abc/trades?week=7&team=x#offer");
    expect(safeNext("/leagues/x/standings?week=3")).toBe("/leagues/x/standings?week=3");
  });
  it.each([
    "//evil.com",
    "/\\evil.com",
    "/.//evil.com",
    "/..//evil.com",
    "/a/..//evil.com",
    "/%2e//evil.com",
    "/\t/evil.com",
    "/\n/evil.com",
    "https://evil.com",
    "javascript:alert(1)",
    "evil.com",
    "",
  ])("refuses %j", (raw) => {
    expect(safeNext(raw)).toBe("/dashboard");
  });
  it("uses the given fallback for null", () => {
    expect(safeNext(null, "/")).toBe("/");
  });
});

describe("loginHref", () => {
  it("sends the guest back to the same page and query", () => {
    expect(loginHref("/draft/d1", "view=board&round=2")).toBe(`/login?next=${encodeURIComponent("/draft/d1?view=board&round=2")}`);
    expect(loginHref("/league/l1", "")).toBe(`/login?next=${encodeURIComponent("/league/l1")}`);
  });
  it("never builds an off-site next", () => {
    expect(loginHref("//evil.com", "")).toBe(`/login?next=${encodeURIComponent("/")}`);
  });
});
