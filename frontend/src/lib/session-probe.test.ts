import { describe, expect, it } from "vitest";
import { hasSessionHintCookie, sessionProbePlan } from "./api-client";

describe("guest auth bootstrap (QA 2026-10-19 NEW-3)", () => {
  it("makes no auth calls for a guest with no session hints", () => {
    expect(sessionProbePlan({ hasSessionCookie: false, hasUserHint: false, hasLegacyToken: false })).toBe("skip");
  });
  it("probes when any hint of a session exists", () => {
    expect(sessionProbePlan({ hasSessionCookie: true, hasUserHint: false, hasLegacyToken: false })).toBe("probe");
    expect(sessionProbePlan({ hasSessionCookie: false, hasUserHint: true, hasLegacyToken: false })).toBe("probe");
    expect(sessionProbePlan({ hasSessionCookie: false, hasUserHint: false, hasLegacyToken: true })).toBe("probe");
  });
  it("detects the ffc_session hint cookie exactly", () => {
    expect(hasSessionHintCookie("")).toBe(false);
    expect(hasSessionHintCookie("theme=dark; ffc_session=1")).toBe(true);
    expect(hasSessionHintCookie("ffc_session=1")).toBe(true);
    expect(hasSessionHintCookie("not_ffc_session=1; x=2")).toBe(false);
  });
});
