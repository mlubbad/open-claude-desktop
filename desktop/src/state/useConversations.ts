// Conversation management layered over useTranscript: the sidebar list, the current
// conversation, create-on-first-send, persistence, open, delete.
// Persistence failures degrade gracefully (the chat still works offline).
//
// Turn lifetime is decoupled from the view (see turnSessions.ts): opening another
// conversation ATTACHES to its session — it never aborts an in-flight turn. A turn
// left streaming in the background finishes on its own and is saved here under its
// own conversation via the store's onTurnEnd callback. The user's message is also
// persisted eagerly at send time, so a prompt can never be lost mid-turn.

import { useCallback, useEffect, useRef, useState } from "react";

import { type ConversationSummary, conversations as convApi, GENERAL_PROJECT } from "../api/client";
import { firstUserText, fromBackend, isFirstExchange, toBackend } from "./persist";
import * as sessions from "./turnSessions";
import { type TurnConfig, useTranscript } from "./useTranscript";

export function useConversations(config: TurnConfig) {
  const chat = useTranscript(config);
  const [list, setList] = useState<ConversationSummary[]>([]);
  const [current, setCurrent] = useState<{ cid: string; pid: string } | null>(null);
  // Persistence problems are surfaced, not swallowed: the sidebar shows this so
  // "history isn't loading" is diagnosable instead of silently empty.
  const [histErr, setHistErr] = useState<string | null>(null);
  const titled = useRef<Set<string>>(new Set());
  // Conversations the user has renamed by hand — an in-flight auto-title must not
  // overwrite a deliberate title.
  const renamedManually = useRef<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      setList(await convApi.listAll());
      setHistErr(null);
    } catch (e) {
      /* backend offline — keep the last list, but say so */
      setHistErr(`Couldn't load history: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Save + auto-title whenever ANY session's turn finishes — including one detached
  // in the background. The store hands us the session's own (key, pid, messages), so
  // the transcript always lands under the conversation the turn belongs to, no matter
  // what is on screen when it completes.
  useEffect(() => {
    sessions.onTurnEnd(({ key, pid, messages }) => {
      if (key === sessions.DRAFT_KEY || messages.length === 0) {
        sessions.disposeIfDetached(key);
        return;
      }
      const save = convApi
        .save(pid, key, toBackend(messages))
        .then(() => refresh())
        .catch(() => {});

      if (!titled.current.has(key) && !renamedManually.current.has(key) && isFirstExchange(messages)) {
        titled.current.add(key);
        const seed = firstUserText(messages);
        if (seed) {
          convApi
            .generateTitle(seed)
            // A manual rename that lands while the title generates wins.
            .then(({ title }) =>
              title && !renamedManually.current.has(key) ? convApi.rename(pid, key, title) : null,
            )
            .then(() => refresh())
            .catch(() => {});
        }
      }
      // Free the session once its transcript is safely persisted — unless the user is
      // looking at it (then it simply IS the live view until they navigate away).
      void save.finally(() => sessions.disposeIfDetached(key));
    });
    return () => sessions.onTurnEnd(null);
  }, [refresh]);

  // Ensure a conversation row exists (created lazily on the first message), stream,
  // and persist the user's message immediately so it survives anything — a crash, a
  // conversation switch, an app quit.
  const send = useCallback(
    async (goal: string) => {
      if (!goal.trim() || chat.busy) return;
      const pid = config.projectId ?? GENERAL_PROJECT;
      let target = current;
      if (!target) {
        try {
          const created = await convApi.create(pid, goal);
          target = { cid: created.id, pid };
          sessions.rekey(sessions.DRAFT_KEY, created.id, pid);
          setCurrent(target);
          void refresh();
        } catch {
          /* offline: proceed without persistence */
        }
      }
      if (!chat.send(goal)) return;
      if (target) {
        // Eager save: the store applied startTurn synchronously, so the active
        // session's messages already include this prompt.
        convApi
          .save(target.pid, target.cid, toBackend(sessions.activeMessages()))
          .then(() => refresh())
          .catch(() => {});
      }
    },
    [current, chat, refresh, config.projectId],
  );

  const openConversation = useCallback(
    async (cid: string, pid: string): Promise<boolean> => {
      // A live session (still streaming, or freshly finished and not yet disposed)
      // is the source of truth — attach to it instead of loading the older server
      // copy. This is what makes "switch away and come back" seamless.
      if (sessions.has(cid)) {
        sessions.setActive(cid, pid);
        setCurrent({ cid, pid });
        setHistErr(null);
        return true;
      }
      try {
        const detail = await convApi.get(pid, cid);
        sessions.loadInto(cid, pid, fromBackend(detail.messages));
        setCurrent({ cid, pid });
        setHistErr(null);
        return true;
      } catch (e) {
        setHistErr(`Couldn't open that chat: ${e instanceof Error ? e.message : String(e)}`);
        return false;
      }
    },
    [],
  );

  const newChat = useCallback(() => {
    sessions.resetDraft(config.projectId ?? GENERAL_PROJECT);
    setCurrent(null);
  }, [config.projectId]);

  // Answer an inline structured-question card: collapse it, then post the composed
  // answer as the next turn (contract §5.1).
  const answerQuestion = useCallback(
    (id: string, text: string) => {
      chat.markQuestionAnswered(id);
      void send(text);
    },
    [chat, send],
  );

  const remove = useCallback(
    async (cid: string, pid: string) => {
      sessions.destroy(cid); // a deleted conversation's background turn dies with it
      try {
        await convApi.del(pid, cid);
      } catch {
        /* ignore */
      }
      if (current?.cid === cid) newChat();
      void refresh();
    },
    [current, newChat, refresh],
  );

  const rename = useCallback(
    async (cid: string, pid: string, title: string) => {
      const t = title.trim();
      if (!t) return;
      renamedManually.current.add(cid); // a hand-picked title outranks auto-titling
      try {
        await convApi.rename(pid, cid, t);
      } catch {
        /* ignore */
      }
      void refresh();
    },
    [refresh],
  );

  const togglePin = useCallback(
    async (cid: string, pid: string, pinned: boolean) => {
      try {
        await convApi.setPinned(pid, cid, pinned);
      } catch {
        /* ignore */
      }
      void refresh();
    },
    [refresh],
  );

  const move = useCallback(
    async (cid: string, pid: string, dstProjectId: string) => {
      if (pid === dstProjectId) return;
      try {
        await convApi.move(pid, cid, dstProjectId);
      } catch {
        /* ignore */
      }
      // Keep the open conversation's project pointer in sync so follow-up saves land
      // right — including a live session's background save.
      sessions.setSessionPid(cid, dstProjectId);
      setCurrent((c) => (c && c.cid === cid ? { cid, pid: dstProjectId } : c));
      void refresh();
    },
    [refresh],
  );

  return {
    state: chat.state,
    busy: chat.busy,
    stop: chat.stop,
    resolveApproval: chat.resolveApproval,
    retryLast: chat.retryLast,
    editAndResend: chat.editAndResend,
    openArtifact: chat.openArtifact,
    closeArtifact: chat.closeArtifact,
    send,
    answerQuestion,
    list,
    histErr,
    current,
    openConversation,
    newChat,
    remove,
    rename,
    togglePin,
    move,
  };
}
