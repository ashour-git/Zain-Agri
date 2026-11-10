import type { ReactNode } from "react";

/*
 * The model answers in light Markdown: paragraphs, **bold**, "-" or "1." lists
 * and pipe tables. This renders exactly that as React elements and nothing
 * else: no HTML is ever injected, so a product name containing markup stays
 * plain text.
 */

function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <strong key={index} className="font-semibold text-ink">
        {part.slice(2, -2)}
      </strong>
    ) : (
      part
    ),
  );
}

const LIST_ITEM = /^\s*(?:[-*•]|\d+[.)])\s+/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_RULE = /^\s*\|?[\s:|-]+\|?\s*$/;

function cells(row: string): string[] {
  return row.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
}

export function RichText({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index] ?? "";

    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (TABLE_ROW.test(line)) {
      const rows: string[][] = [];
      while (index < lines.length && TABLE_ROW.test(lines[index] ?? "")) {
        const current = lines[index] ?? "";
        if (!TABLE_RULE.test(current)) rows.push(cells(current));
        index += 1;
      }
      const [head, ...body] = rows;
      blocks.push(
        <div key={`t${index}`} className="overflow-x-auto rounded-md border border-line">
          <table className="w-full text-[13px]">
            {head ? (
              <thead className="bg-surface/70">
                <tr>
                  {head.map((cell, i) => (
                    <th key={i} className="px-2.5 py-1.5 text-start font-medium text-ink-muted">
                      {inline(cell)}
                    </th>
                  ))}
                </tr>
              </thead>
            ) : null}
            <tbody className="divide-y divide-line">
              {body.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, i) => (
                    <td key={i} className="px-2.5 py-1.5">
                      {inline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    if (LIST_ITEM.test(line)) {
      const items: string[] = [];
      while (index < lines.length && LIST_ITEM.test(lines[index] ?? "")) {
        items.push((lines[index] ?? "").replace(LIST_ITEM, ""));
        index += 1;
      }
      blocks.push(
        <ul key={`l${index}`} className="space-y-1 ps-4 [&>li]:list-disc [&>li]:marker:text-ink-muted">
          {items.map((item, i) => (
            <li key={i}>{inline(item)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    const paragraph: string[] = [];
    while (
      index < lines.length &&
      (lines[index] ?? "").trim() &&
      !TABLE_ROW.test(lines[index] ?? "") &&
      !LIST_ITEM.test(lines[index] ?? "")
    ) {
      paragraph.push(lines[index] ?? "");
      index += 1;
    }
    blocks.push(<p key={`p${index}`}>{inline(paragraph.join(" "))}</p>);
  }

  return <div className="space-y-2.5 leading-relaxed">{blocks}</div>;
}
