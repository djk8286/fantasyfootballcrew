// Player page projection tile vs the live NFL week (QA 2026-10-19: Gibbs
// showed "PROJ WK 5" while the site was on week 6 -- Sleeper simply has no
// week-6 projection for a player on bye, so the last one synced lingered).

export interface ProjectionTile {
  label: string;
  value: number | null; // null -> render "—"
  note?: string;
}

export function projectionTile(
  projectedPoints: number | null,
  projectedWeek: number | null,
  currentWeek: number | null,
  byeWeek: number | null,
): ProjectionTile {
  if (currentWeek == null || projectedWeek == null || projectedWeek >= currentWeek) {
    return { label: `Proj${projectedWeek ? ` wk ${projectedWeek}` : ""}`, value: projectedPoints };
  }
  if (byeWeek === currentWeek) return { label: `Wk ${currentWeek}`, value: null, note: "Bye week" };
  return {
    label: `Proj wk ${currentWeek}`,
    value: null,
    note: projectedPoints != null ? `Not projected yet (wk ${projectedWeek}: ${projectedPoints.toFixed(1)})` : "Not projected yet",
  };
}
