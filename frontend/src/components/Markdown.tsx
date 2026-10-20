// Minimal, safe Markdown for AI output (QA 2026-10-19 BUG K: Trade and Bet
// results showed literal "## Heading", "**bold**", table pipes and
// "([site](url))"). Deliberately tiny and dependency-free:
//  - everything is rendered as React elements, never dangerouslySetInnerHTML,
//    so any HTML in the model's output shows up as inert text;
//  - links only for http(s) URLs (no javascript:/data:), opened in a new tab
//    with rel="noopener noreferrer nofollow"; tracking params are left as-is.
// Supports headings, paragraphs, bullet/numbered lists, GFM tables,
// blockquotes, rules, **bold**, *italic*, `code` and [text](url).
import type { ReactNode } from "react";

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "para"; lines: string[] }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "table"; header: string[]; rows: string[][] }
  | { kind: "quote"; lines: string[] }
  | { kind: "rule" };

const TABLE_SEP = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;
const splitRow = (line: string) =>
  line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

export function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }
    const h = /^(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (h) { blocks.push({ kind: "heading", level: h[1].length, text: h[2] }); i++; continue; }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { blocks.push({ kind: "rule" }); i++; continue; }
    if (line.includes("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1])) {
      const header = splitRow(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(splitRow(lines[i++]));
      blocks.push({ kind: "table", header, rows });
      continue;
    }
    const bullet = /^\s*[-*+]\s+(.*)$/;
    const numbered = /^\s*\d+[.)]\s+(.*)$/;
    if (bullet.test(line) || numbered.test(line)) {
      const ordered = !bullet.test(line);
      const re = ordered ? numbered : bullet;
      const items: string[] = [];
      while (i < lines.length && re.test(lines[i])) items.push(re.exec(lines[i++])![1]);
      blocks.push({ kind: "list", ordered, items });
      continue;
    }
    if (/^\s*>/.test(line)) {
      const q: string[] = [];
      while (i < lines.length && /^\s*>/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
      blocks.push({ kind: "quote", lines: q });
      continue;
    }
    const para: string[] = [];
    while (
      i < lines.length && lines[i].trim() &&
      !/^(#{1,6})\s/.test(lines[i]) && !bullet.test(lines[i]) && !numbered.test(lines[i]) && !/^\s*>/.test(lines[i]) &&
      !(lines[i].includes("|") && i + 1 < lines.length && TABLE_SEP.test(lines[i + 1]))
    ) para.push(lines[i++]);
    blocks.push({ kind: "para", lines: para });
  }
  return blocks;
}

export function safeHref(url: string): string | null {
  try {
    const u = new URL(url.trim());
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

const INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*|__[^_]+__)|((?<!\w)\*[^*\s][^*]*\*(?!\w)|(?<!\w)_[^_\s][^_]*_(?!\w))|(\[[^\]]+\]\([^)\s]+\))/;

export function renderInline(text: string, keyPrefix = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text;
  let k = 0;
  while (rest) {
    const m = INLINE.exec(rest);
    if (!m) { out.push(rest); break; }
    if (m.index > 0) out.push(rest.slice(0, m.index));
    const tok = m[0];
    const key = `${keyPrefix}-${k++}`;
    if (m[1]) out.push(<code key={key} className="px-1 rounded bg-surface-800 text-[0.85em]">{tok.slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={key} className="font-semibold text-white">{renderInline(tok.slice(2, -2), key)}</strong>);
    else if (m[3]) out.push(<em key={key}>{renderInline(tok.slice(1, -1), key)}</em>);
    else {
      const lm = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok)!;
      const href = safeHref(lm[2]);
      out.push(
        href ? (
          <a key={key} href={href} target="_blank" rel="noopener noreferrer nofollow" className="text-gold-400 underline underline-offset-2">
            {lm[1]}
          </a>
        ) : (
          lm[1]
        )
      );
    }
    rest = rest.slice(m.index + tok.length);
  }
  return out;
}

const HEADING_CLASS = ["", "text-lg", "text-base", "text-base", "text-sm", "text-sm", "text-sm"];

export default function Markdown({ text }: { text: string }) {
  return (
    <div className="space-y-3">
      {parseBlocks(text).map((b, n) => {
        const key = `b${n}`;
        switch (b.kind) {
          case "heading": {
            const cls = `${HEADING_CLASS[b.level]} font-semibold text-white mt-2`;
            return b.level <= 2 ? <h3 key={key} className={cls}>{renderInline(b.text, key)}</h3> : <h4 key={key} className={cls}>{renderInline(b.text, key)}</h4>;
          }
          case "rule":
            return <hr key={key} className="border-surface-700" />;
          case "list": {
            const items = b.items.map((it, j) => <li key={j}>{renderInline(it, `${key}-${j}`)}</li>);
            return b.ordered ? (
              <ol key={key} className="list-decimal pl-5 space-y-1">{items}</ol>
            ) : (
              <ul key={key} className="list-disc pl-5 space-y-1">{items}</ul>
            );
          }
          case "table":
            return (
              <div key={key} className="overflow-x-auto">
                <table className="text-left text-xs border-collapse">
                  <thead>
                    <tr>{b.header.map((c, j) => <th key={j} className="px-2 py-1 border-b border-surface-600 font-semibold text-white">{renderInline(c, `${key}-h${j}`)}</th>)}</tr>
                  </thead>
                  <tbody>
                    {b.rows.map((r, j) => (
                      <tr key={j}>{r.map((c, x) => <td key={x} className="px-2 py-1 border-b border-surface-700/60 align-top">{renderInline(c, `${key}-${j}-${x}`)}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "quote":
            return <blockquote key={key} className="border-l-2 border-surface-600 pl-3 text-surface-300">{b.lines.map((l, j) => <p key={j}>{renderInline(l, `${key}-${j}`)}</p>)}</blockquote>;
          default:
            return (
              <p key={key}>
                {b.lines.map((l, j) => (
                  <span key={j}>
                    {j > 0 && <br />}
                    {renderInline(l, `${key}-${j}`)}
                  </span>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
}
