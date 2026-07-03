import { useEffect, useMemo, useRef, useState } from "react";

import { notify, registerSummonHotkey, unregisterSummonHotkey } from "./platform";
import { ApprovalPrompt } from "./components/ApprovalPrompt";
import { ArtifactPanel } from "./components/ArtifactPanel";
import { Composer } from "./components/Composer";
import { AssistantBubble, UserBubble } from "./components/Message";
import { ProjectPanel } from "./components/ProjectPanel";
import { Settings } from "./components/Settings";
import { Sidebar } from "./components/Sidebar";
import { conversationsForProject } from "./state/projectFilter";
import { findArtifact } from "./state/transcript";
import { useConversations } from "./state/useConversations";
import { useKeyboard } from "./state/useKeyboard";
import { useProjects } from "./state/useProjects";

export default function App() {
  const [provider, setProvider] = useState<string>("zhipu");
  const [model, setModel] = useState<string>("glm-4-plus");
  const [showSettings, setShowSettings] = useState(false);
  const [showProject, setShowProject] = useState(false);

  const proj = useProjects();

  const config = useMemo(
    () => ({ provider, model, effort: "High", permissionMode: "ask" as const, projectId: proj.active }),
    [provider, model, proj.active],
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

  // Global summon hotkey (desktop only; no-op on web). Fired from the OS even when the
  // app is unfocused; brings it forward and starts a fresh chat.
  const newChatRef = useRef(newChat);
  newChatRef.current = newChat;
  useEffect(() => {
    const accel = "CmdOrControl+Shift+Space";
    void registerSummonHotkey(accel, () => newChatRef.current());
    return () => void unregisterSummonHotkey(accel);
  }, []);

  // Notify when a response finishes while the window is in the background.
  const prevBusy = useRef(false);
  useEffect(() => {
    if (prevBusy.current && !busy && typeof document !== "undefined" && document.hidden) {
      void notify("Open Claude Desktop", "Your response is ready.");
    }
    prevBusy.current = busy;
  }, [busy]);

  const lastAssistantIdx = state.messages.reduce((acc, m, i) => (m.role === "assistant" ? i : acc), -1);
  const openDoc = findArtifact(state, state.openArtifactId);
  const scopedList = conversationsForProject(list, proj.active);
  const activeProjectName = proj.list.find((p) => p.id === proj.active)?.name ?? "";

  async function newProject() {
    const name = window.prompt("New project name");
    if (name?.trim()) {
      await proj.create(name.trim());
      newChat();
    }
  }

  return (
    <div className="app-shell">
      <Sidebar
        projects={proj.list}
        activeProject={proj.active}
        onSelectProject={(pid) => {
          proj.setActive(pid);
          newChat();
        }}
        onNewProject={newProject}
        onManageProject={() => setShowProject(true)}
        list={scopedList}
        currentId={current?.cid ?? null}
        onNew={newChat}
        onOpen={openConversation}
        onDelete={remove}
      />

      <div className="app">
        <header className="topbar">
          <div className="brand">
            Open Claude Desktop
            {proj.active && <span className="project-chip">{activeProjectName}</span>}
          </div>
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

      {showProject && proj.active && (
        <ProjectPanel
          pid={proj.active}
          name={activeProjectName}
          onClose={() => setShowProject(false)}
          onDelete={async () => {
            await proj.remove(proj.active!);
            setShowProject(false);
            newChat();
          }}
        />
      )}
    </div>
  );
}
