/**
 * The tokens are DESIGN.md's palette, nothing more and nothing less. DESIGN.md is what a person
 * approves (T6.1) and what `verify.py --phase 6` measures; this keeps the CSS from drifting off it.
 */

import { describe, expect, it } from "vitest";

import design from "../../DESIGN.md?raw";
import tokens from "./tokens.css?raw";

const HEX = /`(#[0-9a-fA-F]{6})`/g;

function subsection(text: string, title: string): string {
  const start = text.indexOf(`\n### ${title}\n`);
  if (start < 0) {
    throw new Error(`DESIGN.md has no "### ${title}"`);
  }
  const rest = text.slice(start + 1);
  const end = rest.slice(4).search(/\n#{2,3} /);
  return end < 0 ? rest : rest.slice(0, end + 4);
}

function tableRows(section: string): string[][] {
  return section
    .split("\n")
    .filter((line) => line.startsWith("|"))
    .slice(2)
    .map((line) => line.split("|").slice(1, -1).map((cell) => cell.trim()));
}

const kebab = (name: string) => name.toLowerCase().replaceAll(" ", "-");

/** DESIGN.md's colours by the token they become: `[light, dark]`. */
function designColours(): Map<string, [string, string]> {
  const colours = new Map<string, [string, string]>();
  const tables: [string, string, number][] = [
    ["Named values", "", 1],
    ["Score bar colours", "factor-", 2],
    ["Build-state colours", "state-", 2],
  ];
  for (const [title, prefix, firstHexCell] of tables) {
    for (const row of tableRows(subsection(design, title))) {
      const hexes = [...row.slice(firstHexCell, firstHexCell + 2).join(" ").matchAll(HEX)].map((m) =>
        (m[1] ?? "").toLowerCase(),
      );
      const [light, dark] = hexes;
      if (row[0] && light && dark) {
        colours.set(`--${prefix}${kebab(row[0])}`, [light, dark]);
      }
    }
  }
  return colours;
}

function block(css: string, selector: string): Map<string, string> {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) {
    throw new Error(`tokens.css has no ${selector} block`);
  }
  const body = css.slice(start, css.indexOf("\n}", start));
  const values = new Map<string, string>();
  for (const match of body.matchAll(/^\s*(--[\w-]+):\s*([^;]+);/gm)) {
    values.set(match[1] ?? "", (match[2] ?? "").trim().toLowerCase());
  }
  return values;
}

const light = block(tokens, ":root");
const dark = block(tokens, ':root[data-theme="dark"]');
const colours = designColours();

describe("design tokens", () => {
  it("reads all thirteen of DESIGN.md's colours", () => {
    expect([...colours.keys()]).toEqual([
      "--ground",
      "--panel",
      "--ink",
      "--graphite",
      "--spruce",
      "--plum",
      "--factor-urgency",
      "--factor-dependency",
      "--factor-execution-time",
      "--factor-aging",
      "--state-succeeded",
      "--state-failed",
      "--state-unstable",
    ]);
  });

  it.each([...colours.entries()])("%s has DESIGN.md's value in both themes", (token, [lightHex, darkHex]) => {
    expect(light.get(token)).toBe(lightHex);
    expect(dark.get(token)).toBe(darkHex);
  });

  it("defines no colour that DESIGN.md does not name", () => {
    for (const values of [light, dark]) {
      for (const [token, value] of values) {
        if (/^#[0-9a-f]{3,8}$/.test(value)) {
          expect(colours.has(token), `${token}: ${value}`).toBe(true);
        }
      }
    }
  });

  it("derives Rule from Graphite and Panel, as DESIGN.md says", () => {
    expect(light.get("--rule")).toBe("color-mix(in oklab, var(--graphite) 25%, var(--panel))");
    expect(dark.get("--rule")).toBe("color-mix(in oklab, var(--graphite) 30%, var(--panel))");
    expect(design).toContain("`color-mix(in oklab, Graphite 25%, Panel)`");
  });
});
