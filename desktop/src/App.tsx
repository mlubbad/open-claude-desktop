import { useEffect, useMemo, useRef, useState } from "react";

import { conversations } from "./api/client";
import { notify, onTrayNewChat, registerSummonHotkey, unregisterSummonHotkey } from "./platform";
import { ApprovalPrompt } from "./components/ApprovalPrompt";
import { ArtifactPanel } from "./components/ArtifactPanel";
import { CodePanel } from "./components/CodePanel";
import { CoworkPanel } from "./components/CoworkPanel";
import { type Command, CommandPalette } from "./components/CommandPalette";
import { Composer } from "./components/Composer";
import { ConnectorsPanel } from "./components/ConnectorsPanel";
import { AssistantBubble, UserBubble } from "./components/Message";
import { PluginsPanel } from "./components/PluginsPanel";
import { ProjectPanel } from "./components/ProjectPanel";
import { Settings } from "./components/Settings";
import { ShortcutsHelp } from "./components/ShortcutsHelp";
import { Sidebar } from "./components/Sidebar";
import { UsageMeter } from "./components/UsageMeter";
import { exportSlug, toMarkdown } from "./state/exportConversation";
import { type Drafts, getDraft, setDraft } from "./state/drafts";
import { useAutoScroll } from "./state/useAutoScroll";
import { conversationsForProject } from "./state/projectFilter";
import { STARTER_PROMPTS } from "./state/starters";
import { findArtifact } from "./state/transcript";
import { useCode } from "./state/useCode";
import { useCowork } from "./state/useCowork";
import { useConnectors } from "./state/useConnectors";
import { useConversations } from "./state/useConversations";
import { useKeyboard } from "./state/useKeyboard";
import { usePlugins } from "./state/usePlugins";
import { useProjects } from "./state/useProjects";
import { useSkills } from "./state/useSkills";
import { useTheme } from "./state/useTheme";
import { themeGlyph } from "./state/theme";

export default function App() {
  const [provider, setProvider] = useState<string>("zhipu");
  const [model, setModel] = useState<string>("glm-4-plus");
  const [showSettings, setShowSettings] = useState(false);
  const [showProject, setShowProject] = useState(false);
  const [showConnectors, setShowConnectors] = useState(false);
  const [showPlugins, setShowPlugins] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [view, setView] = useState<"chat" | "code" | "cowork">("chat");
  // Plan mode: the agent researches read-only and proposes a plan to approve before it
  // changes anything. Only meaningful in the interactive Chat/Code views.
  const [planMode, setPlanMode] = useState(false);

  const proj = useProjects();
  const connectors = useConnectors();
  const pluginMgr = usePlugins();
  const skills = useSkills();
  const theme = useTheme();
  const codeWs = useCode(proj.active ?? undefined, view === "code");
  const cowork = useCowork(
    { model, provider, effort: "High", projectId: proj.active },
    view === "cowork",
  );

  const config = useMemo(
    () => ({
      provider,
      model,
      effort: "High",
      permissionMode: planMode ? "plan" : "ask",
      projectId: proj.active,
      enabledMcp: connectors.enabled,
      enabledPlugins: pluginMgr.enabled,
      // In Code mode, give the agent its file + shell tools over the workspace, plus
      // subagents so it can fan out isolated subtasks (reading many files, focused analysis).
      options:
        view === "code"
          ? { text_editor: true, bash: true, code_exec: true, subagents: true }
          : undefined,
    }),
    [provider, model, proj.active, connectors.enabled, pluginMgr.enabled, view, planMode],
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
    rename,
    togglePin,
  } = useConversations(config);

  useKeyboard({
    onEscape: () => (busy ? stop() : showHelp ? setShowHelp(false) : closeArtifact()),
    onNewChat: newChat,
    onPalette: () => setShowPalette(true),
    onHelp: () => setShowHelp(true),
  });

  const commands: Command[] = useMemo(() => {
    const actions: Command[] = [
      { label: "New chat", hint: "⌘⇧O", run: newChat },
      { label: "Open settings & providers", run: () => setShowSettings(true) },
      { label: "Open connectors (MCP)", run: () => setShowConnectors(true) },
      { label: "Keyboard shortcuts", hint: "?", run: () => setShowHelp(true) },
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

  // Tray "New Chat" menu item (desktop only; no-op on web).
  useEffect(() => {
    let unlisten = () => {};
    void onTrayNewChat(() => newChatRef.current()).then((fn) => (unlisten = fn));
    return () => unlisten();
  }, []);

  // Notify when a response finishes while the window is in the background, and refresh
  // the code workspace so any files the agent edited this turn show up.
  const prevBusy = useRef(false);
  useEffect(() => {
    if (prevBusy.current && !busy) {
      if (typeof document !== "undefined" && document.hidden) {
        void notify("Open Claude Desktop", "Your response is ready.");
      }
      if (view === "code") {
        void codeWs.refresh();
        codeWs.reopen();
      }
    }
    prevBusy.current = busy;
  }, [busy, view, codeWs]);

  // Follow streaming content; state.messages changes on each token so this stays pinned.
  const scroll = useAutoScroll<HTMLElement>([state.messages]);

  const lastAssistantIdx = state.messages.reduce((acc, m, i) => (m.role === "assistant" ? i : acc), -1);
  const openDoc = findArtifact(state, state.openArtifactId);
  const scopedList = conversationsForProject(list, proj.active);
  const activeProjectName = proj.list.find((p) => p.id === proj.active)?.name ?? "";

  function exportChat() {
    const title = list.find((c) => c.id === current?.cid)?.title || "Conversation";
    const md = toMarkdown(state.messages, title);
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${exportSlug(title)}.md`;
    a.click();
    URL.revokeObjectURL(url);
  }

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
        onRename={rename}
        onTogglePin={togglePin}
      />

      <div className="app">
        <header className="topbar">
          <div className="brand">
            Open Claude Desktop
            {proj.active && <span className="project-chip">{activeProjectName}</span>}
            <span className="view-toggle">
              <button className={view === "chat" ? "active" : ""} onClick={() => setView("chat")}>
                Chat
              </button>
              <button className={view === "code" ? "active" : ""} onClick={() => setView("code")}>
                Code
              </button>
              <button className={view === "cowork" ? "active" : ""} onClick={() => setView("cowork")}>
                Cowork
              </button>
            </span>
          </div>
          <div className="topbar-right">
            {view !== "cowork" && (
              <button
                className={`icon-btn plan-toggle ${planMode ? "active" : ""}`}
                title={
                  planMode
                    ? "Plan mode ON — the agent proposes a plan before changing anything"
                    : "Plan mode OFF — turn on to review a plan before any changes"
                }
                aria-pressed={planMode}
                onClick={() => setPlanMode((p) => !p)}
              >
                📋 Plan
              </button>
            )}
            {state.usage && <UsageMeter usage={state.usage} />}
            <button
              className="icon-btn"
              title={`Theme: ${themeGlyph(theme.pref).label} (click to change)`}
              onClick={theme.cycle}
            >
              {themeGlyph(theme.pref).icon}
            </button>
            {state.messages.length > 0 && (
              <button className="icon-btn" title="Export chat as Markdown" onClick={exportChat}>
                ⬇
              </button>
            )}
            <button className="icon-btn" title="Connectors (MCP)" onClick={() => setShowConnectors(true)}>
              🔌{connectors.enabled.length > 0 && <span className="badge">{connectors.enabled.length}</span>}
            </button>
            <button className="icon-btn" title="Plugins" onClick={() => setShowPlugins(true)}>
              🧩{pluginMgr.enabled.length > 0 && <span className="badge">{pluginMgr.enabled.length}</span>}
            </button>
            <button className="model-pill" onClick={() => setShowSettings(true)}>
              {provider} · {model}
            </button>
          </div>
        </header>

        {view === "cowork" ? (
          <CoworkPanel
            tasks={cowork.tasks}
            selected={cowork.selected}
            err={cowork.err}
            onStart={cowork.start}
            onOpen={cowork.open}
            onCancel={cowork.cancel}
          />
        ) : (
        <div className={`workarea ${view === "code" ? "with-code" : ""}`}>
          {view === "code" && (
            <CodePanel
              tree={codeWs.tree}
              selected={codeWs.selected}
              file={codeWs.file}
              err={codeWs.err}
              onOpen={codeWs.open}
              onRefresh={codeWs.refresh}
            />
          )}
          <div className="chat-col">
        <main className="transcript" ref={scroll.ref}>
          {state.messages.length === 0 && (
            <div className="empty">
              <h1>How can I help?</h1>
              <p>Bring your own model — pick a provider and key in settings.</p>
              <div className="starters">
                {STARTER_PROMPTS.map((s) => (
                  <button
                    key={s.label}
                    className="starter"
                    disabled={busy}
                    onClick={() => send(s.prompt)}
                  >
                    <span className="starter-icon">{s.icon}</span>
                    {s.label}
                  </button>
                ))}
              </div>
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
            <ApprovalPrompt
              pending={state.pendingApproval}
              onDecide={(d) => {
                // Approving a plan leaves plan mode (matching the backend for that turn).
                if (d === "approve" && state.pendingApproval?.name === "exit_plan_mode") {
                  setPlanMode(false);
                }
                resolveApproval(d);
              }}
            />
          )}
        </main>

        {scroll.showJump && (
          <button className="jump-latest" title="Jump to latest" onClick={scroll.jumpToBottom}>
            ↓
          </button>
        )}

        <footer className="footer">
          <Composer
            busy={busy}
            onSend={send}
            onStop={stop}
            skills={skills}
            draftKey={current?.cid ?? "new"}
            initialText={getDraft(drafts, current?.cid ?? "new")}
            onTextChange={(t) => setDrafts((d) => setDraft(d, current?.cid ?? "new", t))}
          />
        </footer>
          </div>
        </div>
        )}
      </div>

      {openDoc && <ArtifactPanel doc={openDoc} onClose={closeArtifact} />}

      {showHelp && <ShortcutsHelp onClose={() => setShowHelp(false)} />}

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
          onAddOAuth={(name, url) => void connectors.addOAuth(name, url)}
          onAuthorize={(sid) => void connectors.authorize(sid)}
          onRemove={(sid) => void connectors.remove(sid)}
          onToggle={connectors.toggle}
          onClose={() => setShowConnectors(false)}
        />
      )}

      {showPlugins && (
        <PluginsPanel
          installed={pluginMgr.installed}
          market={pluginMgr.market}
          enabled={pluginMgr.enabled}
          err={pluginMgr.err}
          busy={pluginMgr.busy}
          onToggle={pluginMgr.toggle}
          onInstall={(name) => void pluginMgr.install(name)}
          onUninstall={(name) => void pluginMgr.uninstall(name)}
          onClose={() => setShowPlugins(false)}
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
