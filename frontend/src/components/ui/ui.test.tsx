import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { Badge, InjuryTag, PositionChip } from "./Badge";
import { Button } from "./Button";
import { EmptyState } from "./EmptyState";
import { Num } from "./Num";
import { Tabs } from "./Tabs";
import { formatPoints, injuryCode, toPosition } from "./tokens";

const html = (el: React.ReactElement) => renderToStaticMarkup(el);

describe("positions", () => {
  it("normalizes case and aliases to one position", () => {
    expect(toPosition("qb")).toBe("QB");
    expect(toPosition("D/ST")).toBe("DEF");
    expect(toPosition("DST")).toBe("DEF");
    expect(toPosition("OP")).toBe("SUPERFLEX");
    expect(toPosition("BN")).toBeNull();
    expect(toPosition(null)).toBeNull();
  });

  it("PositionChip colors each position from its token and shortens long slot names", () => {
    expect(html(<PositionChip pos="RB" />)).toContain("text-pos-rb");
    expect(html(<PositionChip pos="SUPERFLEX" />)).toContain(">SFLX<");
    expect(html(<PositionChip pos="IDP_FLEX" />)).toContain(">IDP<");
  });

  it("PositionChip shows an unknown position as neutral text instead of dropping it", () => {
    const out = html(<PositionChip pos="BN" />);
    expect(out).toContain(">BN<");
    expect(out).toContain("text-ink-300");
  });
});

describe("injury tags", () => {
  it("maps Sleeper designations to short codes", () => {
    expect(injuryCode("Questionable")).toBe("Q");
    expect(injuryCode("doubtful")).toBe("D");
    expect(injuryCode("Out")).toBe("O");
    expect(injuryCode("IR")).toBe("IR");
    expect(injuryCode("Sus")).toBe("SUS");
    expect(injuryCode("Healthy")).toBeNull();
    expect(injuryCode(null)).toBeNull();
  });

  it("renders nothing for a healthy player, and BYE wins over an injury", () => {
    expect(html(<InjuryTag status={null} />)).toBe("");
    expect(html(<InjuryTag status="Out" />)).toContain(">O<");
    expect(html(<InjuryTag status="Questionable" onBye />)).toContain(">BYE<");
  });
});

describe("numbers", () => {
  it("formats fixed decimals and a dash for missing values", () => {
    expect(formatPoints(14.6)).toBe("14.6");
    expect(formatPoints(128.444, 2)).toBe("128.44");
    expect(formatPoints(0)).toBe("0.0");
    expect(formatPoints(null)).toBe("—");
    expect(formatPoints(Number.NaN)).toBe("—");
    expect(formatPoints(3.5, 1, true)).toBe("+3.5");
    expect(formatPoints(-3.5, 1, true)).toBe("-3.5");
  });

  it("Num renders in the tabular mono utility", () => {
    const out = html(<Num value={102.14} digits={2} />);
    expect(out).toContain("num");
    expect(out).toContain(">102.14<");
  });
});

describe("controls", () => {
  it("Button defaults to type=button so it never submits a form by accident", () => {
    expect(html(<Button>Save</Button>)).toContain('type="button"');
    expect(html(<Button type="submit">Save</Button>)).toContain('type="submit"');
  });

  it("only the primary Button is gold", () => {
    expect(html(<Button variant="primary">Go</Button>)).toContain("bg-gold");
    expect(html(<Button>Go</Button>)).not.toContain("bg-gold");
  });

  it("Tabs marks exactly the selected tab and keeps only it in the tab order", () => {
    const out = html(
      <Tabs
        label="Sections"
        tabs={[{ id: "a", label: "A" }, { id: "b", label: "B" }]}
        value="b"
        onChange={() => {}}
      />,
    );
    expect(out.match(/aria-selected="true"/g)).toHaveLength(1);
    expect(out).toMatch(/aria-selected="true" tabindex="0"[^>]*>B</);
    expect(out).toMatch(/aria-selected="false" tabindex="-1"[^>]*>A</);
  });

  it("EmptyState always renders its next action", () => {
    const out = html(<EmptyState title="No moves yet" action={<button type="button">Browse free agents</button>} />);
    expect(out).toContain("No moves yet");
    expect(out).toContain("Browse free agents");
  });

  it("Badge uses the tone's color", () => {
    expect(html(<Badge tone="win">W</Badge>)).toContain("text-win");
  });
});
