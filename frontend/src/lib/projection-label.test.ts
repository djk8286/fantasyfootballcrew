import { describe, expect, it } from "vitest";
import { projectionTile } from "./projection-label";

describe("projectionTile", () => {
  it("shows the projection when it's for the current week", () => {
    expect(projectionTile(18.2, 6, 6, 8)).toEqual({ label: "Proj wk 6", value: 18.2 });
  });
  it("never labels a stale week as the projection (bye)", () => {
    expect(projectionTile(21.4, 5, 6, 6)).toEqual({ label: "Wk 6", value: null, note: "Bye week" });
  });
  it("flags a not-yet-synced current week instead of showing last week's number", () => {
    expect(projectionTile(21.4, 5, 6, 9)).toEqual({ label: "Proj wk 6", value: null, note: "Not projected yet (wk 5: 21.4)" });
  });
  it("falls back to the stored week when the live week is unknown", () => {
    expect(projectionTile(10, 5, null, null)).toEqual({ label: "Proj wk 5", value: 10 });
  });
});
