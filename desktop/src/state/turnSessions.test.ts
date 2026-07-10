// Regression tests for the lost-turn-on-switch bug: sending a prompt in conversation
// A, switching to B mid-stream, and returning to A must NOT cancel the turn or lose
// the prompt — the detached session keeps streaming and reports for auto-save.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentEvent } from "../api/events";
import { answerText, type AssistantMessage, type Message, type UserMessage } from "./transcript";
import * as store from "./turnSessions";

interface FakeStream {
  req: unknown;
  onEvent: (ev: AgentEvent) => void;
  ctrl: AbortController;
}

const BASE = {
  model: "m",
  provider: null,
  effort: "High",
  permission_mode: null,
  project_id: "general",
  options: {},
  enabled_mcp: [],
  enabled_plugins: [],
};

const PRIOR: Message[] = [
  { role: "user", text: "audit the site" },
  { role: "assistant", blocks: [{ kind: "answer", text: "Stopped after the step limit." }] } as AssistantMessage,
];

let streams: FakeStream[];

beforeEach(() => {
  streams = [];
  store.__resetForTests();
  store.__setStreamImplForTests(((req: unknown, onEvent: (ev: AgentEvent) => void) => {
    const ctrl = new AbortController();
    streams.push({ req, onEvent, ctrl });
    return ctrl;
  }) as never);
});

afterEach(() => store.__resetForTests());

function lastAnswer(messages: Message[]): string {
  const m = messages[messages.length - 1] as AssistantMessage;
  return answerText(m);
}

describe("turnSessions — the video scenario", () => {
  it("keeps the turn streaming after switching away, and the full transcript is there on return", () => {
    const ended: { key: string; pid: string; messages: Message[] }[] = [];
    store.onTurnEnd((s) => ended.push(s));

    // In the SEO conversation, send "Try again" while it streams.
    store.loadInto("seo", "general", PRIOR);
    expect(store.sendActive("Try again", BASE)).toBe(true);
    expect(store.isBusy("seo")).toBe(true);
    streams[0].onEvent({ type: "answer_open" } as AgentEvent);
    streams[0].onEvent({ type: "delta", scope: "answer", text: "Auditing " } as AgentEvent);

    // Switch to another conversation mid-stream: the SEO stream must NOT be aborted.
    store.loadInto("bq", "general", []);
    expect(streams[0].ctrl.signal.aborted).toBe(false); // <- the old bug: this aborted
    expect(store.isBusy("seo")).toBe(true);

    // The detached session keeps consuming events in the background...
    streams[0].onEvent({ type: "delta", scope: "answer", text: "the site now." } as AgentEvent);
    streams[0].onEvent({ type: "done" } as AgentEvent);

    // ...and reports for auto-save under ITS OWN conversation when it finishes.
    expect(ended).toHaveLength(1);
    expect(ended[0].key).toBe("seo");
    expect(ended[0].pid).toBe("general");
    const msgs = ended[0].messages;
    expect((msgs[2] as UserMessage).text).toBe("Try again"); // the prompt is never lost
    expect(lastAnswer(msgs)).toBe("Auditing the site now.");

    // Returning re-attaches to the finished session: everything is on screen.
    store.setActive("seo", "general");
    const snap = store.getSnapshot();
    expect(snap.key).toBe("seo");
    expect(snap.busy).toBe(false);
    expect((snap.state.messages[2] as UserMessage).text).toBe("Try again");
    expect(lastAnswer(snap.state.messages)).toBe("Auditing the site now.");
  });

  it("returning MID-stream shows the prompt + partial answer, still busy", () => {
    store.loadInto("seo", "general", PRIOR);
    store.sendActive("Try again", BASE);
    streams[0].onEvent({ type: "answer_open" } as AgentEvent);
    streams[0].onEvent({ type: "delta", scope: "answer", text: "Working…" } as AgentEvent);

    store.loadInto("bq", "general", []); // away
    store.setActive("seo", "general"); // and back, before the turn ends

    const snap = store.getSnapshot();
    expect(snap.busy).toBe(true);
    expect((snap.state.messages[2] as UserMessage).text).toBe("Try again");
    expect(lastAnswer(snap.state.messages)).toBe("Working…");

    // Live events continue rendering into the re-attached view.
    streams[0].onEvent({ type: "delta", scope: "answer", text: " done." } as AgentEvent);
    expect(lastAnswer(store.getSnapshot().state.messages)).toBe("Working… done.");
  });

  it("the prompt is in the session state synchronously at send (eager-save source)", () => {
    store.loadInto("seo", "general", PRIOR);
    store.sendActive("Try again", BASE);
    const msgs = store.activeMessages();
    expect((msgs[2] as UserMessage).text).toBe("Try again");
  });
});

describe("turnSessions — lifecycle", () => {
  it("notifies subscribers only for the active session", () => {
    const cb = vi.fn();
    const unsub = store.subscribe(cb);
    store.loadInto("seo", "general", []);
    store.sendActive("go", BASE);
    store.loadInto("bq", "general", []);
    const before = cb.mock.calls.length;
    streams[0].onEvent({ type: "delta", scope: "answer", text: "background" } as AgentEvent);
    expect(cb.mock.calls.length).toBe(before); // background event: no re-render churn
    unsub();
  });

  it("stopActive stops only the active session; a detached one keeps going", () => {
    store.loadInto("seo", "general", []);
    store.sendActive("a", BASE);
    store.loadInto("bq", "general", []);
    store.sendActive("b", BASE);
    store.stopActive(); // stops bq (active)
    expect(streams[1].ctrl.signal.aborted).toBe(true);
    expect(store.isBusy("bq")).toBe(false);
    expect(streams[0].ctrl.signal.aborted).toBe(false); // seo untouched
    expect(store.isBusy("seo")).toBe(true);
  });

  it("rekey moves a draft session (and the active view) to the real conversation id", () => {
    store.resetDraft("general");
    store.sendActive("hello", BASE);
    store.rekey(store.DRAFT_KEY, "c1", "general");
    expect(store.has("c1")).toBe(true);
    expect(store.has(store.DRAFT_KEY)).toBe(false);
    expect(store.getSnapshot().key).toBe("c1");
    expect((store.activeMessages()[0] as UserMessage).text).toBe("hello");
  });

  it("rekey on a FRESH store (no draft session yet) still pins the turn to the real id", () => {
    // First send on a fresh mount: useConversations creates the row and rekeys
    // BEFORE anything has touched the store. The turn must stream under the real
    // conversation id — under "draft" it would be orphaned by the next New chat.
    store.rekey(store.DRAFT_KEY, "c9", "general");
    expect(store.sendActive("first message", BASE)).toBe(true);
    expect(store.isBusy("c9")).toBe(true);

    store.resetDraft("general"); // New chat mid-stream must not orphan it
    streams[0].onEvent({ type: "answer_open" } as AgentEvent);
    streams[0].onEvent({ type: "delta", scope: "answer", text: "still alive" } as AgentEvent);
    expect(store.isBusy("c9")).toBe(true);
    expect(streams[0].ctrl.signal.aborted).toBe(false);

    store.setActive("c9", "general");
    expect(lastAnswer(store.getSnapshot().state.messages)).toBe("still alive");
  });

  it("destroy aborts a deleted conversation's background turn", () => {
    store.loadInto("seo", "general", []);
    store.sendActive("go", BASE);
    store.loadInto("bq", "general", []);
    store.destroy("seo");
    expect(streams[0].ctrl.signal.aborted).toBe(true);
    expect(store.has("seo")).toBe(false);
  });

  it("an idle session is disposed on switch-away; a finished detached one after dispose call", () => {
    store.loadInto("seo", "general", PRIOR);
    store.loadInto("bq", "general", []); // seo idle -> disposed
    expect(store.has("seo")).toBe(false);

    store.sendActive("x", BASE); // bq streams
    store.loadInto("other", "general", []);
    streams[0].onEvent({ type: "done" } as AgentEvent); // bq finishes detached
    store.disposeIfDetached("bq");
    expect(store.has("bq")).toBe(false);
    // ...but never disposes the session the user is looking at.
    store.disposeIfDetached("other");
    expect(store.has("other")).toBe(true);
  });

  it("a stream failure ends the turn and still reports the partial transcript", () => {
    const ended: { key: string; messages: Message[] }[] = [];
    store.onTurnEnd((s) => ended.push(s));
    let failStream: (() => void) | undefined;
    store.__setStreamImplForTests(((_req: unknown, onEvent: (ev: AgentEvent) => void, onError?: () => void) => {
      streams.push({ req: _req, onEvent, ctrl: new AbortController() } as FakeStream);
      failStream = onError;
      return new AbortController();
    }) as never);
    store.loadInto("seo", "general", []);
    store.sendActive("go", BASE);
    streams[0].onEvent({ type: "answer_open" } as AgentEvent);
    streams[0].onEvent({ type: "delta", scope: "answer", text: "partial" } as AgentEvent);
    failStream?.();
    expect(store.isBusy("seo")).toBe(false);
    expect(ended).toHaveLength(1);
    expect(lastAnswer(ended[0].messages)).toBe("partial"); // partial content saved, not lost
  });
});
