import { describe, expect, it } from "vitest";
import { ownerLabel, teamOwnershipText } from "./owner-label";

const base = { commissionerId: "commish", isOwnerMe: false, isCoOwnerMe: false };

describe("ownerLabel (guest view)", () => {
  it("labels the commissioner's team Commish even for a logged-out viewer", () => {
    expect(ownerLabel({ ...base, ownerId: "commish" }).label).toBe("Commish");
  });
  it("labels other human teams Claimed, not Joined", () => {
    expect(ownerLabel({ ...base, ownerId: "u2" }).label).toBe("Claimed");
    expect(ownerLabel({ ...base, ownerId: "u2", coOwnerId: "u3" }).label).toBe("Claimed (2 owners)");
  });
  it("labels CPU and placeholder teams", () => {
    expect(ownerLabel({ ...base, ownerId: "cpu" }).label).toBe("CPU");
    expect(ownerLabel({ ...base, ownerId: "x", isCpu: true }).label).toBe("CPU");
    expect(ownerLabel({ ...base, ownerId: "placeholder" }).label).toBe("Unclaimed");
  });
});

describe("ownerLabel (member view)", () => {
  it("shows You for the viewer's own team", () => {
    expect(ownerLabel({ ...base, ownerId: "me", isOwnerMe: true }).label).toBe("You");
    expect(ownerLabel({ ...base, ownerId: "o", coOwnerId: "me", isCoOwnerMe: true }).label).toBe("You (Co-Owner)");
  });
});

describe("teamOwnershipText", () => {
  it("never says Owner-managed", () => {
    expect(teamOwnershipText({ ...base, ownerId: "u2" })).toBe("Claimed by a league member");
    expect(teamOwnershipText({ ...base, ownerId: "commish" })).toBe("Commissioner's team");
    expect(teamOwnershipText({ ...base, ownerId: "placeholder" })).toBe("Unclaimed");
    expect(teamOwnershipText({ ...base, ownerId: "me", isOwnerMe: true })).toBe("You own this team");
  });
});
