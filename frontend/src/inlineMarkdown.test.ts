import { describe, expect, it } from "vitest";
import { parseCopilotContent, parseInlineMarkdown } from "./inlineMarkdown";

describe("parseInlineMarkdown", () => {
  it("parses bold and italic LLM output without returning delimiters", () => {
    expect(parseInlineMarkdown("Use **cash flow** and *monthly* totals.")).toEqual([
      { style: "plain", text: "Use " },
      { style: "bold", text: "cash flow" },
      { style: "plain", text: " and " },
      { style: "italic", text: "monthly" },
      { style: "plain", text: " totals." },
    ]);
  });

  it("supports combined bold italic emphasis", () => {
    expect(parseInlineMarkdown("This is ***important***.")).toEqual([
      { style: "plain", text: "This is " },
      { style: "boldItalic", text: "important" },
      { style: "plain", text: "." },
    ]);
  });

  it("leaves unmatched asterisks as plain text", () => {
    expect(parseInlineMarkdown("A *partial response")).toEqual([
      { style: "plain", text: "A *partial response" },
    ]);
  });
});

describe("parseCopilotContent", () => {
  it("extracts a Markdown pipe table from surrounding prose", () => {
    expect(parseCopilotContent([
      "Here is the comparison:",
      "",
      "| Category | Monthly amount |",
      "| :--- | ---: |",
      "| Food | **$450** |",
      "| Transit | $120 |",
      "",
      "Keep an eye on food.",
    ].join("\n"))).toEqual([
      { type: "text", content: "Here is the comparison:\n" },
      {
        type: "table",
        headers: ["Category", "Monthly amount"],
        rows: [["Food", "**$450**"], ["Transit", "$120"]],
      },
      { type: "text", content: "\nKeep an eye on food." },
    ]);
  });

  it("leaves non-table pipes untouched", () => {
    expect(parseCopilotContent("Cash | investments")).toEqual([
      { type: "text", content: "Cash | investments" },
    ]);
  });
});
