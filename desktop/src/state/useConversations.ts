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
  const prevBusy = useRef(false);
  const titled = useRef<Set<string>>(new Set());

  const refresh = useCallback(async () => {
    try {
      setList(await convApi.listAll());
    } catch {
      /* backend offline — keep the last list */
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

  // Auto-save the transcript when a turn transitions from running -> idle, and
  // auto-title the conversation once, right after its first exchange completes.
  useEffect(() => {
    if (prevBusy.current && !chat.busy && current && chat.state.messages.length > 0) {
      convApi
        .save(current.pid, current.cid, toBackend(chat.state.messages))
        .then(() => refresh())
        .catch(() => {});

      if (!titled.current.has(current.cid) && isFirstExchange(chat.state.messages)) {
        titled.current.add(current.cid);
        const seed = firstUserText(chat.state.messages);
        if (seed) {
          const { pid, cid } = current;
          convApi
            .generateTitle(seed)
            .then(({ title }) => (title ? convApi.rename(pid, cid, title) : null))
            .then(() => refresh())
            .catch(() => {});
        }
      }
    }
    prevBusy.current = chat.busy;
  }, [chat.busy, current, chat.state.messages, refresh]);

  const openConversation = useCallback(
    async (cid: string, pid: string) => {
      try {
        const detail = await convApi.get(pid, cid);
        chat.load(fromBackend(detail.messages));
        setCurrent({ cid, pid });
      } catch {
        /* ignore */
      }
    },
    [chat],
  );

  const newChat = useCallback(() => {
    chat.reset();
    setCurrent(null);
  }, [chat]);

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
    list,
    current,
    openConversation,
    newChat,
    remove,
    rename,
    togglePin,
  };
}
