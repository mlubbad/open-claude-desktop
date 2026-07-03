// Conversation management layered over useTranscript: the sidebar list, the current
// conversation, create-on-first-send, auto-save when a turn finishes, open, delete.
// Persistence failures degrade gracefully (the chat still works offline).

import { useCallback, useEffect, useRef, useState } from "react";

import { type ConversationSummary, conversations as convApi, GENERAL_PROJECT } from "../api/client";
import { fromBackend, toBackend } from "./persist";
import { type TurnConfig, useTranscript } from "./useTranscript";

export function useConversations(config: TurnConfig) {
  const chat = useTranscript(config);
  const [list, setList] = useState<ConversationSummary[]>([]);
  const [current, setCurrent] = useState<{ cid: string; pid: string } | null>(null);
  const prevBusy = useRef(false);

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
        try {
          const created = await convApi.create(GENERAL_PROJECT, goal);
          setCurrent({ cid: created.id, pid: GENERAL_PROJECT });
          void refresh();
        } catch {
          /* offline: proceed without persistence */
        }
      }
      chat.send(goal);
    },
    [current, chat, refresh],
  );

  // Auto-save the transcript when a turn transitions from running -> idle.
  useEffect(() => {
    if (prevBusy.current && !chat.busy && current && chat.state.messages.length > 0) {
      convApi
        .save(current.pid, current.cid, toBackend(chat.state.messages))
        .then(() => refresh())
        .catch(() => {});
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

  return {
    state: chat.state,
    busy: chat.busy,
    stop: chat.stop,
    resolveApproval: chat.resolveApproval,
    send,
    list,
    current,
    openConversation,
    newChat,
    remove,
  };
}
