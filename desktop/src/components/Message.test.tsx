// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AssistantMessage } from "../state/transcript";
import { AssistantBubble } from "./Message";

function msg(extra: Partial<AssistantMessage>): AssistantMessage {
  return { role: "assistant", blocks: [{ kind: "answer", text: "done", streaming: false }], ...extra };
}

describe("AssistantBubble harness rendering", () => {
  it("renders nothing extra when the message has no harness activity", () => {
    render(<AssistantBubble msg={msg({})} isLast={false} busy={false} />);
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("renders the tool timeline from accumulated tool_call events", () => {
    render(
      <AssistantBubble
        msg={msg({ toolCalls: [{ id: "c1", name: "read_file", ok: true }] })}
        isLast={false}
        busy={false}
      />,
    );
    expect(screen.getByText(/read_file/)).toBeInTheDocument();
  });

  it("renders a FileDiffCard per accumulated file_diff", () => {
    render(
      <AssistantBubble
        msg={msg({
          fileDiffs: [
            { id: "c1", diff: "--- a\n+++ a\n+added" },
            { id: "c2", diff: "--- b\n+++ b\n-removed" },
          ],
        })}
        isLast={false}
        busy={false}
      />,
    );
    expect(screen.getByText(/\+added/)).toBeInTheDocument();
    expect(screen.getByText(/-removed/)).toBeInTheDocument();
  });

  it("renders the plan card from the latest plan_update", () => {
    render(
      <AssistantBubble
        msg={msg({ planItems: [{ id: 1, subject: "write the tests", status: "in_progress" }] })}
        isLast={false}
        busy={false}
      />,
    );
    expect(screen.getByText("write the tests")).toBeInTheDocument();
  });

  it("does not render RewindMenu without an onRestoreCheckpoint handler, even with a checkpoint", () => {
    render(
      <AssistantBubble
        msg={msg({ checkpointTurnId: "t1", workspaceId: "ws-1" })}
        isLast={false}
        busy={false}
      />,
    );
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  // Review regression: a message can (in principle) have a checkpoint but no stamped
  // workspaceId -- must not render a RewindMenu with nothing to restore against.
  it("does not render RewindMenu when the message has a checkpoint but no workspaceId", () => {
    const onRestoreCheckpoint = vi.fn();
    render(
      <AssistantBubble
        msg={msg({ checkpointTurnId: "t1" })}
        isLast={false}
        busy={false}
        onRestoreCheckpoint={onRestoreCheckpoint}
      />,
    );
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("renders RewindMenu when a checkpoint, a workspaceId, and a handler are all present, and passes THIS message's workspaceId through", () => {
    const onRestoreCheckpoint = vi.fn();
    render(
      <AssistantBubble
        msg={msg({ checkpointTurnId: "t1", workspaceId: "ws-1" })}
        isLast={false}
        busy={false}
        onRestoreCheckpoint={onRestoreCheckpoint}
      />,
    );
    fireEvent.click(screen.getByText(/restore files/i));
    // The message's OWN workspaceId ("ws-1"), not any live/ambient workspace state --
    // the whole point of the review fix (rewind targets the workspace the message's
    // turn actually ran under).
    expect(onRestoreCheckpoint).toHaveBeenCalledWith("ws-1", "t1", "files");
  });
});
