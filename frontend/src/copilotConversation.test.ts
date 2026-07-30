import { describe, expect, it } from "vitest";
import { branchConversation, type CopilotMessage } from "./copilotConversation";

const conversation: CopilotMessage[] = [
  { id: "u1", role: "user", content: "First question" },
  { id: "a1", role: "assistant", content: "First answer" },
  { id: "u2", role: "user", content: "Follow-up" },
  { id: "a2", role: "assistant", content: "Follow-up answer" },
];

describe("branchConversation", () => {
  it("resends a prompt and removes all later turns", () => {
    expect(branchConversation(conversation, "u2", undefined, "u3")).toEqual([
      { id: "u1", role: "user", content: "First question" },
      { id: "a1", role: "assistant", content: "First answer" },
      { id: "u3", role: "user", content: "Follow-up" },
    ]);
  });

  it("edits a prompt before creating the new branch", () => {
    expect(branchConversation(conversation, "u1", "  Better question  ", "u3")).toEqual([
      { id: "u3", role: "user", content: "Better question" },
    ]);
  });

  it("rejects assistant messages and blank edits", () => {
    expect(branchConversation(conversation, "a1", undefined, "x")).toBeNull();
    expect(branchConversation(conversation, "u1", "   ", "x")).toBeNull();
  });

  it("preserves image attachments when resending a user turn", () => {
    const withImage: CopilotMessage[] = [
      {
        id: "u1",
        role: "user",
        content: "Read my planner",
        attachment_ids: ["image-1"],
      },
      { id: "a1", role: "assistant", content: "I found two events." },
    ];
    expect(branchConversation(withImage, "u1", undefined, "u2")).toEqual([
      {
        id: "u2",
        role: "user",
        content: "Read my planner",
        attachment_ids: ["image-1"],
      },
    ]);
  });
});
