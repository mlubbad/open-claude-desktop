import { useEffect, useMemo, useRef, useState } from "react";

import { conversations } from "./api/client";
import { notify, registerSummonHotkey, unregisterSummonHotkey } from "./platform";
import { ApprovalPrompt } from "./components/ApprovalPrompt";
import { ArtifactPanel } from "./components/ArtifactPanel";
import { type Command, CommandPalette } from "./components/CommandPalette";
import { Composer } from "./components/Composer";
import { ConnectorsPanel } from "./components/ConnectorsPanel";
import { AssistantBubble, UserBubble } from "./components/Message";
import { ProjectPanel } from "./components/ProjectPanel";
import { Settings } from "./components/Settings";
import { Sidebar } from "./components/Sidebar";
import { UsageMeter } from "./components/UsageMeter";
import { conversationsForProject } from "./state/projectFilter";
import { findArtifact } from "./state/transcript";
import { useConnectors } from "./state/useConnectors";
import { useConversations } from "./state/useConversations";
import { useKeyboard } from "./state/useKeyboard";
import { useProjects } from "./state/useProjects";

export default function App() {
  const [provider, setProvider] = useState<string>("zhipu");
  const [model, setModel] = useState<string>("glm-4-plus");
  const [showSettings, setShowSettings] = useState(false);
  const [showProject, setShowProject] = useState(false);
  const [showConnectors, setShowConnectors] = useState(false);
  const [showPalette, setShowPalette] = useState(false);

  const proj = useProjects();
  const connectors = useConnectors();

  const config = useMemo(
    () => ({
      provider,
      model,
      effort: "High",
      permissionMode: "ask" as const,
      projectId: proj.active,
      enabledMcp: connectors.enabled,
    }),
    [provider, model, proj.active, connectors.enabled],
  );
  const {
    state,
    busy,
    send,
    retryLast,
    editAndResend,
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

  useKeyboard({
    onEscape: () => (busy ? stop() : closeArtifact()),
    onNewChat: newChat,
    onPalette: () => setShowPalette(true),
  });

  const commands: Command[] = useMemo(() => {
    const actions: Command[] = [
      { label: "New chat", hint: "⌘⇧O", run: newChat },
      { label: "Open settings & providers", run: () => setShowSettings(true) },
      { label: "Open connectors (MCP)", run: () => setShowConnectors(true) },
    ];
    if (proj.active) actions.push({ label: "Manage current project", run: () => setShowProject(true) });
    const chats: Command[] = list.map((c) => ({
      label: `Chat: ${c.title || "Untitled"}`,
      hint: c.updated_rel,
      run: () => openConversation(c.id, c.project_id ?? "general"),
    }));
    return [...actions, ...chats];
  }, [newChat, proj.active, list, openConversation]);

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
          <div className="topbar-right">
            {state.usage && <UsageMeter usage={state.usage} />}
            <button className="icon-btn" title="Connectors (MCP)" onClick={() => setShowConnectors(true)}>
              🔌{connectors.enabled.length > 0 && <span className="badge">{connectors.enabled.length}</span>}
            </button>
            <button className="model-pill" onClick={() => setShowSettings(true)}>
              {provider} · {model}
            </button>
          </div>
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
              <UserBubble key={i} msg={m} onEdit={busy ? undefined : (text) => editAndResend(i, text)} />
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

      {showPalette && (
        <CommandPalette
          commands={commands}
          search={async (q) => {
            const hits = await conversations.search(q);
            // Body matches only — title matches are already in the command list above.
            return hits
              .filter((h) => h.matched_in !== "title")
              .map((h) => ({
                label: `Chat: ${h.title || "Untitled"}`,
                hint: h.updated_rel,
                sub: h.snippet,
                run: () => openConversation(h.id, h.project_id ?? "general"),
              }));
          }}
          onClose={() => setShowPalette(false)}
        />
      )}

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

      {showConnectors && (
        <ConnectorsPanel
          servers={connectors.servers}
          enabled={connectors.enabled}
          err={connectors.err}
          onAdd={(body) => void connectors.add(body)}
          onAddDemo={() => void connectors.addDemo()}
          onInstall={(file) => void connectors.install(file)}
          onRemove={(sid) => void connectors.remove(sid)}
          onToggle={connectors.toggle}
          onClose={() => setShowConnectors(false)}
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
