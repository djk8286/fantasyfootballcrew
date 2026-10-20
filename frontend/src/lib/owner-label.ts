// Ownership labels for team lists / team pages. Pure so it's testable and
// so guests and members see the same facts: the commissioner's team is
// "Commish" for everyone (it used to depend on the *viewer* being the
// commissioner, so guests saw it as "Joined"), and other people's teams say
// "Claimed" rather than the ambiguous "Joined"/"Owner-managed" (QA LO3).

export interface OwnerLabelInput {
  ownerId: string | null | undefined;
  coOwnerId?: string | null;
  isCpu?: boolean;
  commissionerId?: string | null;
  isOwnerMe: boolean;
  isCoOwnerMe: boolean;
}

export interface OwnerLabel {
  label: string;
  isHuman: boolean;
  isMe: boolean;
  isCommish: boolean;
}

export function ownerLabel(i: OwnerLabelInput): OwnerLabel {
  if (i.isCpu || i.ownerId === "cpu") return { label: "CPU", isHuman: false, isMe: false, isCommish: false };
  if (!i.ownerId || i.ownerId === "placeholder") return { label: "Unclaimed", isHuman: false, isMe: false, isCommish: false };
  const isCommish = !!i.commissionerId && i.ownerId === i.commissionerId;
  if (i.isOwnerMe || i.isCoOwnerMe) {
    const label = i.isCoOwnerMe && !i.isOwnerMe ? "You (Co-Owner)" : i.coOwnerId ? "You + Co-Owner" : "You";
    return { label, isHuman: true, isMe: true, isCommish };
  }
  if (isCommish) return { label: "Commish", isHuman: true, isMe: false, isCommish: true };
  return { label: i.coOwnerId ? "Claimed (2 owners)" : "Claimed", isHuman: true, isMe: false, isCommish: false };
}

/** One-line ownership text for the team page header (non-CPU teams). */
export function teamOwnershipText(i: OwnerLabelInput): string {
  const o = ownerLabel(i);
  if (o.isMe) return i.isOwnerMe ? "You own this team" : "You co-own this team";
  if (o.label === "Unclaimed") return "Unclaimed";
  if (o.isCommish) return "Commissioner's team";
  return "Claimed by a league member";
}
