import { useMemo, useState } from "react";

import { ApprovalPrompt } from "./components/ApprovalPrompt";
import { ArtifactPanel } from "./components/ArtifactPanel";
import { Composer } from "./components/Composer";
import { AssistantBubble, UserBubble } from "./components/Message";
import { Settings } from "./components/Settings";
import { Sidebar } from "./components/Sidebar";
import { findArtifact } from "./state/transcript";
import { useConversations } from "./state/useConversations";
import { useKeyboard } from "./state/useKeyboard";

export default function App() {
  const [provider, setProvider] = useState<string>("zhipu");
  const [model, setModel] = useState<string>("glm-4-plus");
  const [showSettings, setShowSettings] = useState(false);

  const config = useMemo(
    () => ({ provider, model, effort: "High", permissionMode: "ask" as const }),
    [provider, model],
  );
  const {
    state,
    busy,
    send,
    retryLast,
    stop,
    resolveApproval,
    openArtifact,
    closeArtifact,
    list,
    current,
    openConversation,
    newChat,
    remove,
  } = useConversations(config);

  useKeyboard({ onEscape: () => (busy ? stop() : closeArtifact()), onNewChat: newChat });

  const lastAssistantIdx = state.messages.reduce(
    (acc, m, i) => (m.role === "assistant" ? i : acc),
    -1,
  );
  const openDoc = findArtifact(state, state.openArtifactId);

  return (
    <div className="app-shell">
      <Sidebar
        list={list}
        currentId={current?.cid ?? null}
        onNew={newChat}
        onOpen={openConversation}
        onDelete={remove}
      />

      <div className="app">
        <header className="topbar">
          <div className="brand">Open Claude Desktop</div>
          <button className="model-pill" onClick={() => setShowSettings(true)}>
            {provider} · {model}
          </button>
        </header>

        <main className="transcript">
          {state.messages.length === 0 && (
            <div className="empty">
              <h1>How can I help?</h1>
              <p>Bring your own model — pick a provider and key in settings.</p>
            </div>
          )}
          {state.messages.map((m, i) =>
            m.role === "user" ? (
              <UserBubble key={i} msg={m} />
            ) : (
              <AssistantBubble
                key={i}
                msg={m}
                isLast={i === lastAssistantIdx}
                busy={busy}
                onRetry={retryLast}
                onOpenArtifact={openArtifact}
              />
            ),
          )}
          {state.error && <div className="turn-error">{state.error}</div>}
          {state.pendingApproval && (
            <ApprovalPrompt pending={state.pendingApproval} onDecide={resolveApproval} />
          )}
        </main>

        <footer className="footer">
          <Composer busy={busy} onSend={send} onStop={stop} />
        </footer>
      </div>

      {openDoc && <ArtifactPanel doc={openDoc} onClose={closeArtifact} />}

      {showSettings && (
        <Settings
          active={{ provider, model }}
          onPick={(p, m) => {
            setProvider(p);
            setModel(m);
          }}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}
