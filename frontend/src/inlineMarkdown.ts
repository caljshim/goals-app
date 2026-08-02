export type InlineMarkdownStyle = "plain" | "bold" | "italic" | "boldItalic";

export type InlineMarkdownSegment = {
  style: InlineMarkdownStyle;
  text: string;
};

export type CopilotContentBlock =
  | { type: "text"; content: string }
  | { type: "table"; headers: string[]; rows: string[][] };

const emphasisPattern = /(\*\*\*([\s\S]+?)\*\*\*|\*\*([\s\S]+?)\*\*|\*([^*\n]+?)\*)/g;

export function parseInlineMarkdown(content: string): InlineMarkdownSegment[] {
  const segments: InlineMarkdownSegment[] = [];
  let cursor = 0;

  for (const match of content.matchAll(emphasisPattern)) {
    const index = match.index;
    if (index > cursor) {
      segments.push({ style: "plain", text: content.slice(cursor, index) });
    }

    if (match[2] !== undefined) {
      segments.push({ style: "boldItalic", text: match[2] });
    } else if (match[3] !== undefined) {
      segments.push({ style: "bold", text: match[3] });
    } else {
      segments.push({ style: "italic", text: match[4] });
    }
    cursor = index + match[0].length;
  }

  if (cursor < content.length) {
    segments.push({ style: "plain", text: content.slice(cursor) });
  }
  return segments;
}

export function parseCopilotContent(content: string): CopilotContentBlock[] {
  const lines = content.split("\n");
  const blocks: CopilotContentBlock[] = [];
  let textLines: string[] = [];

  const flushText = () => {
    if (textLines.length > 0) {
      blocks.push({ type: "text", content: textLines.join("\n") });
      textLines = [];
    }
  };

  for (let index = 0; index < lines.length;) {
    const headers = parsePipeRow(lines[index]);
    const separator = index + 1 < lines.length ? parsePipeRow(lines[index + 1]) : null;
    const isTable = headers !== null
      && headers.length >= 2
      && separator?.length === headers.length
      && separator.every((cell) => /^:?-{3,}:?$/.test(cell));

    if (!isTable || !headers) {
      textLines.push(lines[index]);
      index += 1;
      continue;
    }

    const rows: string[][] = [];
    index += 2;
    while (index < lines.length) {
      const row = parsePipeRow(lines[index]);
      if (!row || row.length !== headers.length) break;
      rows.push(row);
      index += 1;
    }

    if (rows.length === 0) {
      textLines.push(lines[index - 2], lines[index - 1]);
      continue;
    }
    flushText();
    blocks.push({ type: "table", headers, rows });
  }

  flushText();
  return blocks;
}

function parsePipeRow(line: string): string[] | null {
  let value = line.trim();
  if (!value.includes("|")) return null;
  if (value.startsWith("|")) value = value.slice(1);
  if (value.endsWith("|")) value = value.slice(0, -1);

  const cells: string[] = [];
  let cell = "";
  let escaped = false;
  for (const character of value) {
    if (escaped) {
      cell += character;
      escaped = false;
    } else if (character === "\\") {
      escaped = true;
    } else if (character === "|") {
      cells.push(cell.trim());
      cell = "";
    } else {
      cell += character;
    }
  }
  if (escaped) cell += "\\";
  cells.push(cell.trim());
  return cells;
}
