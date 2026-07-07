// Conversation management layered over useTranscript: the sidebar list, the current
// conversation, create-on-first-send, auto-save when a turn finishes, open, delete.
// Persistence failures degrade gracefully (the chat still works offline).

import { useCallback, useEffect, useRef, useState } from "react";

import { type ConversationSummary, conversations as convApi, GENERAL_PROJECT } from "../api/client";
import { firstUserText, fromBackend, isFirstExchange, toBackend } from "./persist";
import { type TurnConfig, useTranscript } from "./useTranscript";

export function useConversations(config: TurnConfig) {
  const chat = useTranscript(config);
  const [list, setList] = useState<ConversationSummary[]>([]);
  const [current, setCurrent] = useState<{ cid: string; pid: string } | null>(null);
  // Persistence problems are surfaced, not swallowed: the sidebar shows this so
  // "history isn't loading" is diagnosable instead of silently empty.
  const [histErr, setHistErr] = useState<string | null>(null);
  // The turn's (busy, cid) from last render: auto-save fires only when a turn ends
  // in the SAME conversation it started in — switching chats mid-stream must never
  // save the replacement transcript (or auto-title it) under the wrong thread.
  const prevTurn = useRef<{ busy: boolean; cid: string | null }>({ busy: false, cid: null });
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

  // Ensure a conversation row exists (created lazily on the first message), then stream.
  const send = useCallback(
    async (goal: string) => {
      if (!goal.trim() || chat.busy) return;
      if (!current) {
        const pid = config.projectId ?? GENERAL_PROJECT;
        try {
          const created = await convApi.create(pid, goal);
          setCurrent({ cid: created.id, pid });
          void refresh();
        } catch {
          /* offline: proceed without persistence */
        }
      }
      chat.send(goal);
    },
    [current, chat, refresh, config.projectId],
  );

  // Auto-save the transcript when a turn transitions from running -> idle in the
  // same conversation, and auto-title the conversation once, right after its first
  // exchange completes.
  useEffect(() => {
    const prev = prevTurn.current;
    const sameThread = current && prev.cid === current.cid;
    if (prev.busy && !chat.busy && current && sameThread && chat.state.messages.length > 0) {
      convApi
        .save(current.pid, current.cid, toBackend(chat.state.messages))
        .then(() => refresh())
        .catch(() => {});

      if (
        !titled.current.has(current.cid) &&
        !renamedManually.current.has(current.cid) &&
        isFirstExchange(chat.state.messages)
      ) {
        titled.current.add(current.cid);
        const seed = firstUserText(chat.state.messages);
        if (seed) {
          const { pid, cid } = current;
          convApi
            .generateTitle(seed)
            // A manual rename that lands while the title generates wins.
            .then(({ title }) =>
              title && !renamedManually.current.has(cid) ? convApi.rename(pid, cid, title) : null,
            )
            .then(() => refresh())
            .catch(() => {});
        }
      }
    }
    prevTurn.current = { busy: chat.busy, cid: current?.cid ?? null };
  }, [chat.busy, current, chat.state.messages, refresh]);

  const openConversation = useCallback(
    async (cid: string, pid: string): Promise<boolean> => {
      try {
        const detail = await convApi.get(pid, cid);
        chat.load(fromBackend(detail.messages));
        setCurrent({ cid, pid });
        setHistErr(null);
        return true;
      } catch (e) {
        setHistErr(`Couldn't open that chat: ${e instanceof Error ? e.message : String(e)}`);
        return false;
      }
    },
    [chat],
  );

  const newChat = useCallback(() => {
    chat.reset();
    setCurrent(null);
  }, [chat]);

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
  };
}
