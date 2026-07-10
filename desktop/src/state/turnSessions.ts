// Per-conversation turn sessions, decoupled from the visible view.
//
// Previously the live turn (transcript state + SSE AbortController) lived inside the
// mounted useTranscript hook, so opening another conversation HAD to abort the stream
// (its events would otherwise graft onto the replacement transcript) — which cancelled
// the in-flight turn server-side and, because nothing had persisted the just-sent user
// message, the prompt vanished entirely when the user returned. This store fixes that
// at the root: each conversation owns a session whose stream keeps consuming into its
// OWN TranscriptState (via the pure reducers in transcript.ts) no matter what is on
// screen. Switching conversations merely changes which session the view subscribes to;
// a detached session finishes in the background and reports through onTurnEnd so it is
// saved under its own conversation — matching Claude Desktop behaviour.
//
// The view subscribes via useSyncExternalStore (see useTranscript.ts): listeners are
// notified only for mutations of the ACTIVE session (background sessions mutate
// silently), plus whenever the active key changes.

import { type AgentTurnRequest, replyPermission, streamTurn } from "../api/client";
import type { AgentEvent } from "../api/events";
import { openExternal } from "../platform";
import {
  answerQuestionState,
  applyEvent,
  buildHistory,
  editFrom,
  initialState,
  lastUserIndex,
  loadMessages,
  type Message,
  resolveApprovalState,
  restoreApprovalState,
  retryFrom,
  startTurn,
  type TranscriptState,
  type UserMessage,
} from "./transcript";

// The key for a chat that has no conversation row yet (created lazily on first send;
// rekey()ed to the real conversation id as soon as one exists).
export const DRAFT_KEY = "draft";

// Everything a turn request needs except goal/history (which the store derives from
// the session state at launch time). Built by the hook from the current TurnConfig.
export type BaseTurnRequest = Omit<AgentTurnRequest, "goal" | "history">;

interface Session {
  key: string;
  pid: string;
  state: TranscriptState;
  busy: boolean;
  ctrl: AbortController | null;
  // auth_url auto-open fires AT MOST ONCE per tool call (replay/reconnect guard).
  openedAuth: Set<string>;
}

// The immutable snapshot handed to React — rebuilt on every active-session mutation
// so useSyncExternalStore sees a new reference exactly when a re-render is needed.
export interface SessionSnap {
  key: string;
  state: TranscriptState;
  busy: boolean;
}

const sessions = new Map<string, Session>();
let activeKey: string = DRAFT_KEY;
const listeners = new Set<() => void>();

// Fired whenever ANY session's turn finishes (done/error/stop/stream failure) —
// regardless of whether it is attached. useConversations registers the auto-save +
// auto-title handler here, keyed by the session's own conversation, so a background
// turn persists under the right thread.
type TurnEndHandler = (s: { key: string; pid: string; messages: Message[] }) => void;
let onTurnEndHandler: TurnEndHandler | null = null;

// Injectable for tests (a controllable fake stream / permission reply).
let streamImpl = streamTurn;
let replyPermissionImpl = replyPermission;

function fresh(key: string, pid: string, state?: TranscriptState): Session {
  return { key, pid, state: state ?? initialState(), busy: false, ctrl: null, openedAuth: new Set() };
}

function ensure(key: string, pid: string): Session {
  let s = sessions.get(key);
  if (!s) {
    s = fresh(key, pid);
    sessions.set(key, s);
  }
  return s;
}

let snap: SessionSnap = { key: activeKey, state: initialState(), busy: false };

function rebuildSnap(): void {
  const s = ensure(activeKey, "");
  snap = { key: s.key, state: s.state, busy: s.busy };
}

function notify(): void {
  rebuildSnap();
  for (const l of listeners) l();
}

function touched(key: string): void {
  if (key === activeKey) notify();
}

// ---------------------------------------------------------------------------
//  Subscription API (consumed by useTranscript via useSyncExternalStore)
// ---------------------------------------------------------------------------
export function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function getSnapshot(): SessionSnap {
  return snap;
}

export function onTurnEnd(cb: TurnEndHandler | null): void {
  onTurnEndHandler = cb;
}

// ---------------------------------------------------------------------------
//  Session lifecycle (consumed by useConversations)
// ---------------------------------------------------------------------------
export function has(key: string): boolean {
  return sessions.has(key);
}

export function isBusy(key: string): boolean {
  return sessions.get(key)?.busy ?? false;
}

/** Switch the view to `key`. The previous session keeps streaming if busy (that is
 *  the whole point); if idle it is disposed — the server copy is authoritative. */
export function setActive(key: string, pid: string): void {
  const prev = activeKey;
  if (prev !== key) {
    const p = sessions.get(prev);
    if (p && !p.busy) sessions.delete(prev);
  }
  activeKey = key;
  ensure(key, pid).pid = pid || sessions.get(key)!.pid;
  notify();
}

/** Replace `key`'s transcript with server-loaded messages and make it active.
 *  Only for sessions with no live turn (callers attach to busy ones instead). */
export function loadInto(key: string, pid: string, messages: Message[]): void {
  sessions.set(key, fresh(key, pid, loadMessages(messages)));
  setActive(key, pid);
}

/** Fresh empty draft (New chat). Any previous idle session is disposed by setActive.
 *  A BUSY draft can only exist when creating the conversation row failed (offline) —
 *  it has no identity to live on under, so it is aborted rather than orphaned. */
export function resetDraft(pid: string): void {
  const prev = sessions.get(DRAFT_KEY);
  if (prev?.busy) prev.ctrl?.abort();
  sessions.set(DRAFT_KEY, fresh(DRAFT_KEY, pid));
  setActive(DRAFT_KEY, pid);
}

/** Move a session under a new key (draft -> real conversation id on first send).
 *  When no `from` session exists yet (first send on a fresh mount, before anything
 *  touched the store), still move the ACTIVE PIN so the upcoming turn streams under
 *  the real conversation id — otherwise it would run keyed "draft" and be orphaned
 *  by the next New-chat reset. */
export function rekey(from: string, to: string, pid: string): void {
  if (from === to) return;
  const s = sessions.get(from);
  if (!s) {
    if (activeKey === from) {
      activeKey = to;
      ensure(to, pid);
      notify();
    }
    return;
  }
  sessions.delete(from);
  s.key = to;
  s.pid = pid;
  sessions.set(to, s);
  if (activeKey === from) {
    activeKey = to;
    notify();
  }
}

/** Repoint a session's project (conversation moved) so later saves land right. */
export function setSessionPid(key: string, pid: string): void {
  const s = sessions.get(key);
  if (s) s.pid = pid;
}

/** Kill a session outright (conversation deleted): abort its stream, drop its state. */
export function destroy(key: string): void {
  const s = sessions.get(key);
  if (!s) return;
  s.ctrl?.abort();
  sessions.delete(key);
  if (key === activeKey) notify();
}

/** Drop a finished session that is no longer on screen (post-save cleanup). */
export function disposeIfDetached(key: string): void {
  const s = sessions.get(key);
  if (s && !s.busy && key !== activeKey) sessions.delete(key);
}

export function activeMessages(): Message[] {
  return ensure(activeKey, "").state.messages;
}

export function activePid(): string {
  return ensure(activeKey, "").pid;
}

// ---------------------------------------------------------------------------
//  Turn actions (consumed by useTranscript; all address a session BY KEY so a
//  background session's stream keeps mutating the right state)
// ---------------------------------------------------------------------------
function apply(key: string, next: (s: TranscriptState) => TranscriptState): void {
  const s = sessions.get(key);
  if (!s) return; // session destroyed mid-stream (conversation deleted)
  s.state = next(s.state);
  touched(key);
}

function finishTurn(key: string): void {
  const s = sessions.get(key);
  if (!s || !s.busy) return; // idempotent — done event + onError can both land
  s.busy = false;
  s.ctrl = null;
  touched(key);
  onTurnEndHandler?.({ key: s.key, pid: s.pid, messages: s.state.messages });
}

function launch(key: string, goal: string, history: ReturnType<typeof buildHistory>, base: BaseTurnRequest): void {
  const s = sessions.get(key);
  if (!s) return;
  const req: AgentTurnRequest = { ...base, goal, history };
  s.busy = true;
  touched(key);
  s.ctrl = streamImpl(
    req,
    (ev: AgentEvent) => {
      apply(key, (st) => applyEvent(st, ev));
      // The `authenticate` tool asked for browser consent — send the user there, but
      // only once per tool call (guard against replayed/duplicate events). This fires
      // even for a detached session: the background turn is blocked on that consent.
      if (ev.type === "auth_url") {
        const sess = sessions.get(key);
        if (sess && !sess.openedAuth.has(ev.id)) {
          sess.openedAuth.add(ev.id);
          void openExternal(ev.url);
        }
      }
      if (ev.type === "done" || ev.type === "error") finishTurn(key);
    },
    () => finishTurn(key), // stream failure = turn over (partial content still saved)
  );
}

/** Send on the active session. Returns false when refused (busy / empty). */
export function sendActive(goal: string, base: BaseTurnRequest): boolean {
  const key = activeKey;
  const s = ensure(key, base.project_id ?? "");
  if (s.busy || !goal.trim()) return false;
  const history = buildHistory(s.state.messages);
  apply(key, (st) => startTurn(st, goal));
  launch(key, goal, history, base);
  return true;
}

/** Regenerate the most recent assistant response (active session). */
export function retryActive(base: BaseTurnRequest): void {
  const key = activeKey;
  const s = sessions.get(key);
  if (!s || s.busy) return;
  const idx = lastUserIndex(s.state.messages);
  if (idx < 0) return;
  const goal = (s.state.messages[idx] as UserMessage).text;
  const history = buildHistory(s.state.messages.slice(0, idx));
  apply(key, (st) => retryFrom(st, idx));
  launch(key, goal, history, base);
}

/** Edit a prior user message and re-run from there (active session). */
export function editActive(index: number, text: string, base: BaseTurnRequest): void {
  const key = activeKey;
  const s = sessions.get(key);
  if (!s || s.busy || !text.trim()) return;
  const history = buildHistory(s.state.messages.slice(0, index));
  apply(key, (st) => editFrom(st, index, text));
  launch(key, text, history, base);
}

/** Stop the ACTIVE session's turn (the composer's stop button). */
export function stopActive(): void {
  const key = activeKey;
  const s = sessions.get(key);
  if (!s) return;
  s.ctrl?.abort();
  apply(key, (st) => applyEvent(st, { type: "done" }));
  finishTurn(key);
}

/** Approve/decline the active session's pending HITL prompt. */
export async function resolveApprovalActive(decision: "approve" | "decline"): Promise<void> {
  const key = activeKey;
  const s = sessions.get(key);
  const p = s?.state.pendingApproval;
  if (!s || !p) return;
  // Dismiss immediately — the stream's follow-up events carry the real outcome. The
  // id pins the dispatch to THIS approval in case another one arrives first.
  apply(key, (st) => resolveApprovalState(st, decision, p.toolCallId));
  try {
    await replyPermissionImpl(p.turnId, p.toolCallId, decision);
  } catch {
    // Never reached the backend (it will time out as a decline) — re-arm the prompt
    // in the session that owned it, even if the user has since switched away.
    apply(key, (st) => restoreApprovalState(st, p));
  }
}

export function markQuestionAnsweredActive(id: string): void {
  apply(activeKey, (st) => answerQuestionState(st, id));
}

export function setArtifactPanelActive(artifactId: string | null): void {
  apply(activeKey, (st) => ({ ...st, openArtifactId: artifactId }));
}

// ---------------------------------------------------------------------------
//  Test hooks
// ---------------------------------------------------------------------------
export function __setStreamImplForTests(fn: typeof streamTurn): void {
  streamImpl = fn;
}
export function __setReplyPermissionForTests(fn: typeof replyPermission): void {
  replyPermissionImpl = fn;
}
export function __resetForTests(): void {
  for (const s of sessions.values()) s.ctrl?.abort();
  sessions.clear();
  activeKey = DRAFT_KEY;
  onTurnEndHandler = null;
  rebuildSnap();
}
