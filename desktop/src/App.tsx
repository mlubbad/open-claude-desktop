import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { conversations, settings as settingsApi } from "./api/client";
import { notify, onTrayNewChat, registerSummonHotkey, unregisterSummonHotkey } from "./platform";
import { ApprovalPrompt } from "./components/ApprovalPrompt";
import { ArtifactPanel } from "./components/ArtifactPanel";
import { ChatMenu } from "./components/ChatMenu";
import { CodePanel } from "./components/CodePanel";
import { CoworkPanel } from "./components/CoworkPanel";
import { type Command, CommandPalette } from "./components/CommandPalette";
import { type AddMenuInfo, Composer, type ModelControlInfo } from "./components/Composer";
import type { VoiceInfo } from "./components/MicPicker";
import { Icon } from "./components/Icon";
import { InfoPanel } from "./components/InfoPanel";
import { AssistantBubble, UserBubble } from "./components/Message";
import { ProjectPanel } from "./components/ProjectPanel";
import { SettingsModal, type SettingsPage } from "./components/SettingsModal";
import { ShortcutsHelp } from "./components/ShortcutsHelp";
import { Sidebar } from "./components/Sidebar";
import { UsageMeter } from "./components/UsageMeter";
import { type ChatOptions, DEFAULT_CHAT_OPTIONS } from "./state/chatOptions";
import { greeting } from "./state/greeting";
import { exportSlug, toMarkdown } from "./state/exportConversation";
import { type Drafts, getDraft, setDraft } from "./state/drafts";
import { useAutoScroll } from "./state/useAutoScroll";
import { STARTER_GROUPS } from "./state/starters";
import { findArtifact, listArtifacts } from "./state/transcript";
import { useCode } from "./state/useCode";
import { useCowork } from "./state/useCowork";
import { useConnectors } from "./state/useConnectors";
import { useConversations } from "./state/useConversations";
import { useKeyboard } from "./state/useKeyboard";
import { usePlugins } from "./state/usePlugins";
import { useProjectDetail, useProjects } from "./state/useProjects";
import { useSchedules } from "./state/useSchedules";
import { useSkills } from "./state/useSkills";
import { useTheme } from "./state/useTheme";
import { themeGlyph } from "./state/theme";

export default function App() {
  // Chat settings model (contract §8): `active` is what the composer shows for the
  // open conversation; `defaults` is the baseline new chats inherit; `convOverrides`
  // persists each conversation's own model/effort/toggles. An effect below syncs
  // `active` whenever the open conversation changes.
  const [defaults, setDefaults] = useState<ChatOptions>(DEFAULT_CHAT_OPTIONS);
  const [active, setActive] = useState<ChatOptions>(DEFAULT_CHAT_OPTIONS);
  const [convOverrides, setConvOverrides] = useState<Record<string, ChatOptions>>({});
  // Voice / input-device selection (contract §4).
  const [micDeviceId, setMicDeviceId] = useState<string | null>(null);
  const [holdToRecord, setHoldToRecord] = useState(false);
  // First name for the personalized greeting (from the saved profile).
  const [profileName, setProfileName] = useState("");
  // One unified Settings modal; non-null = open at that page (deep-linkable).
  const [settingsPage, setSettingsPage] = useState<SettingsPage | null>(null);
  const [showProject, setShowProject] = useState(false);
  const [showPalette, setShowPalette] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [view, setView] = useState<"chat" | "code" | "cowork">("chat");
  // Plan mode: the agent researches read-only and proposes a plan to approve before it
  // changes anything. Only meaningful in the interactive Chat/Code views.
  const [planMode, setPlanMode] = useState(false);
  // The conversation info rail (artifacts + project knowledge), toggled from the top bar.
  const [showInfo, setShowInfo] = useState(false);

  const proj = useProjects();
  const connectors = useConnectors();
  const pluginMgr = usePlugins();
  const skills = useSkills();
  const theme = useTheme();
  const codeWs = useCode(proj.active ?? undefined, view === "code");
  const cowork = useCowork(
    { model: defaults.model, provider: defaults.provider, effort: defaults.effort, projectId: proj.active },
    view === "cowork",
  );
  const sched = useSchedules(
    { model: defaults.model, provider: defaults.provider, effort: defaults.effort, projectId: proj.active },
    view === "cowork",
  );

  const config = useMemo(
    () => ({
      provider: active.provider,
      model: active.model,
      effort: active.effort,
      permissionMode: planMode ? "plan" : "ask",
      projectId: proj.active,
      enabledMcp: connectors.enabled,
      enabledPlugins: pluginMgr.enabled,
      // Capability toggles: web search / research gate real tools; Code mode adds the
      // file + shell + subagent tools over the workspace.
      options: {
        web_search: active.webSearch,
        research: active.research,
        ...(view === "code"
          ? { text_editor: true, bash: true, code_exec: true, subagents: true }
          : {}),
      },
    }),
    [active, proj.active, connectors.enabled, pluginMgr.enabled, view, planMode],
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
    histErr,
    current,
    openConversation,
    newChat,
    remove,
    rename,
    togglePin,
  } = useConversations(config);

  // Sync the composer's live settings when the open conversation changes: load that
  // conversation's saved settings, or fall back to the workspace defaults for a new
  // chat. Keyed on the conversation id only.
  const currentCid = current?.cid ?? null;
  useEffect(() => {
    setActive(currentCid && convOverrides[currentCid] ? convOverrides[currentCid] : defaults);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentCid]);

  // Apply a settings change to the open conversation (persisting its override) or,
  // for a not-yet-created chat, to the workspace defaults.
  const applyOptions = useCallback(
    (patch: Partial<ChatOptions>) => {
      setActive((prev) => {
        const next = { ...prev, ...patch };
        if (currentCid) setConvOverrides((o) => ({ ...o, [currentCid]: next }));
        else setDefaults(next);
        return next;
      });
    },
    [currentCid],
  );

  // Load the saved profile name + default model/effort once, for the greeting and the
  // new-chat baseline.
  useEffect(() => {
    settingsApi
      .get()
      .then((s) => {
        setProfileName(s.profile?.call_me || s.profile?.name || "");
        const seeded = (d: ChatOptions): ChatOptions => ({
          ...d,
          provider: s.provider ?? d.provider,
          model: s.model ?? d.model,
          effort: s.effort ?? d.effort,
        });
        setDefaults(seeded);
        setActive(seeded); // no conversation open yet at mount → the composer shows these
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Project knowledge for the info rail (loaded only while the rail is open).
  const projDetail = useProjectDetail(showInfo ? proj.active : null);

  // Opening a chat also switches into its project so the breadcrumb, knowledge
  // grounding, and follow-up sends all match where the conversation lives. The
  // project only switches once the chat actually loaded — a failed open must not
  // leave the visible chat grounded on a different project.
  const setActiveProject = proj.setActive;
  const openFromRecents = useCallback(
    async (cid: string, pid: string) => {
      if (await openConversation(cid, pid)) {
        setActiveProject(pid === "general" ? null : pid);
      }
    },
    [openConversation, setActiveProject],
  );

  useKeyboard({
    // Escape closes the topmost open layer first; stopping generation comes after
    // dismissals so a stray Esc while a modal is open never kills the turn.
    onEscape: () =>
      settingsPage
        ? setSettingsPage(null)
        : showProject
          ? setShowProject(false)
          : showHelp
            ? setShowHelp(false)
            : busy
              ? stop()
              : closeArtifact(),
    onNewChat: newChat,
    onPalette: () => setShowPalette(true),
    onHelp: () => setShowHelp(true),
  });

  const commands: Command[] = useMemo(() => {
    const actions: Command[] = [
      { label: "New chat", hint: "⌘⇧O", run: newChat },
      { label: "Settings: models & keys", run: () => setSettingsPage("providers") },
      { label: "Settings: connectors (MCP)", run: () => setSettingsPage("connectors") },
      { label: "Settings: plugins", run: () => setSettingsPage("plugins") },
      { label: "Settings: skills", run: () => setSettingsPage("skills") },
      { label: "Keyboard shortcuts", hint: "?", run: () => setShowHelp(true) },
    ];
    if (proj.active) actions.push({ label: "Manage current project", run: () => setShowProject(true) });
    const chats: Command[] = list.map((c) => ({
      label: `Chat: ${c.title || "Untitled"}`,
      hint: c.updated_rel,
      run: () => void openFromRecents(c.id, c.project_id ?? "general"),
    }));
    return [...actions, ...chats];
  }, [newChat, proj.active, list, openFromRecents]);

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
  const artifacts = listArtifacts(state.messages);
  const activeProjectName = proj.list.find((p) => p.id === proj.active)?.name ?? "";
  // Personalized, context-aware empty-state greeting (time-of-day + first name).
  const greet = useMemo(() => greeting(profileName), [profileName]);

  // Composer control wiring (contract §2/§3/§4). Model + effort persist per
  // conversation via applyOptions; Research / Web-search flow into the request options.
  const addMenu: AddMenuInfo = {
    onAddToProject: () => setShowProject(true),
    onAddFromGitHub: () => setSettingsPage("connectors"),
    openSkills: () => setSettingsPage("skills"),
    openConnectors: () => setSettingsPage("connectors"),
    openPlugins: () => setSettingsPage("plugins"),
    research: active.research,
    onResearch: (on) => applyOptions({ research: on }),
    webSearch: active.webSearch,
    onWebSearch: (on) => applyOptions({ webSearch: on }),
  };
  const modelControl: ModelControlInfo = {
    provider: active.provider,
    model: active.model,
    effort: active.effort,
    thinking: active.thinking,
    onSelectModel: (p, m) => applyOptions({ provider: p, model: m }),
    onSelectEffort: (e) => applyOptions({ effort: e }),
    onToggleThinking: (on) => applyOptions({ thinking: on }),
    onMoreModels: () => setSettingsPage("providers"),
  };
  const voice: VoiceInfo = {
    deviceId: micDeviceId,
    onSelectDevice: setMicDeviceId,
    holdToRecord,
    onHoldToRecord: setHoldToRecord,
    onVoiceMode: () => setSettingsPage("providers"),
  };

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

  async function newProject(name: string) {
    if (name.trim()) {
      await proj.create(name.trim());
      newChat();
    }
  }

  const convTitle = list.find((c) => c.id === current?.cid)?.title;

  return (
    <div className="app-shell">
      <Sidebar
        view={view}
        onView={setView}
        projects={proj.list}
        activeProject={proj.active}
        onSelectProject={(pid) => {
          proj.setActive(pid);
          newChat();
        }}
        onNewProject={(name) => void newProject(name)}
        onManageProject={() => setShowProject(true)}
        list={list}
        currentId={current?.cid ?? null}
        err={histErr ?? proj.err}
        onNew={newChat}
        onOpen={openFromRecents}
        onDelete={remove}
        onRename={rename}
        onTogglePin={togglePin}
        onCustomize={() => setSettingsPage("general")}
        modelLabel={`${defaults.provider} · ${defaults.model}`}
      />

      <div className="app">
        <header className="topbar">
          <div className="topbar-crumbs">
            {proj.active && view !== "cowork" && (
              <>
                <button className="crumb-proj" title="Manage project" onClick={() => setShowProject(true)}>
                  {activeProjectName}
                </button>
                <span className="crumb-sep" aria-hidden="true">/</span>
              </>
            )}
            {view !== "cowork" && current && state.messages.length > 0 ? (
              <ChatMenu
                title={convTitle || "Untitled"}
                onRename={(t) => void rename(current.cid, current.pid, t)}
                onExport={exportChat}
                onDelete={() => void remove(current.cid, current.pid)}
              />
            ) : (
              <span className="crumb-title-static">
                {view === "cowork" ? "Cowork" : state.messages.length > 0 ? convTitle || "Untitled" : ""}
              </span>
            )}
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
                Plan
              </button>
            )}
            {state.usage && <UsageMeter usage={state.usage} />}
            <button
              className="icon-btn icon-only"
              title={`Theme: ${themeGlyph(theme.pref).label} (click to change)`}
              aria-label={`Theme: ${themeGlyph(theme.pref).label}`}
              onClick={theme.cycle}
            >
              <Icon name={themeGlyph(theme.pref).icon} />
            </button>
            {view !== "cowork" && (
              // Pressed state reflects what's actually visible: an open artifact
              // suppresses the rail, and clicking then brings the rail forward.
              <button
                className={`icon-btn icon-only ${showInfo && !openDoc ? "active" : ""}`}
                title="Conversation info — artifacts & project knowledge"
                aria-label="Toggle conversation info panel"
                aria-pressed={showInfo && !openDoc}
                onClick={() => {
                  if (openDoc) {
                    closeArtifact();
                    setShowInfo(true);
                  } else {
                    setShowInfo((s) => !s);
                  }
                }}
              >
                <Icon name="panel" />
              </button>
            )}
          </div>
        </header>

        {view === "cowork" ? (
          <CoworkPanel
            tasks={cowork.tasks}
            selected={cowork.selected}
            err={cowork.err}
            sched={{ items: sched.items, err: sched.err, add: sched.add, remove: sched.remove, toggle: sched.toggle }}
            projectName={proj.active ? activeProjectName : "General"}
            onStart={cowork.start}
            onOpen={cowork.open}
            onBack={cowork.close}
            onCancel={cowork.cancel}
          />
        ) : (
        <div className={`workarea ${view === "code" && state.messages.length > 0 ? "with-code" : ""}`}>
          {/* Code home is composer-forward (hero); the tree+viewer appears once work starts. */}
          {view === "code" && state.messages.length > 0 && (
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
        {state.messages.length === 0 ? (
          <main className="hero">
            <div className="hero-inner">
              <h1 className="hero-greet">
                <span className="hero-mark" aria-hidden="true" />
                {greet}
              </h1>
              <div className="hero-composer">
                <Composer
                  busy={busy}
                  onSend={send}
                  onStop={stop}
                  skills={skills}
                  draftKey={current?.cid ?? "new"}
                  initialText={getDraft(drafts, current?.cid ?? "new")}
                  onTextChange={(t) => setDrafts((d) => setDraft(d, current?.cid ?? "new", t))}
                  placeholder="How can I help you today?"
                  addMenu={addMenu}
                  modelControl={modelControl}
                  voice={voice}
                />
              </div>
              <div className="chips">
                {STARTER_GROUPS.map((s) => (
                  <button
                    key={s.label}
                    className={`chip ${s.wide ? "chip-wide" : ""}`}
                    disabled={busy}
                    onClick={() => send(s.prompt)}
                  >
                    <span className="chip-icon"><Icon name={s.icon} size={14} /></span>
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          </main>
        ) : (
        <main className="transcript" ref={scroll.ref}>
          {state.messages.map((m, i) =>
            m.role === "user" ? (
              <UserBubble key={`${current?.cid ?? "new"}-${i}`} msg={m} onEdit={busy ? undefined : (text) => editAndResend(i, text)} />
            ) : (
              // Keyed per conversation so per-message local state (feedback votes,
              // edit drafts) never leaks across chat switches.
              <AssistantBubble
                key={`${current?.cid ?? "new"}-${i}`}
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
        )}

        {state.messages.length > 0 && scroll.showJump && (
          <button className="jump-latest" title="Jump to latest" aria-label="Jump to latest" onClick={scroll.jumpToBottom}>
            <Icon name="arrow-down" size={15} />
          </button>
        )}

        {state.messages.length > 0 && (
          <footer className="footer">
            <Composer
              busy={busy}
              onSend={send}
              onStop={stop}
              skills={skills}
              draftKey={current?.cid ?? "new"}
              initialText={getDraft(drafts, current?.cid ?? "new")}
              onTextChange={(t) => setDrafts((d) => setDraft(d, current?.cid ?? "new", t))}
              addMenu={addMenu}
              modelControl={modelControl}
              voice={voice}
            />
            <p className="footer-note">AI can make mistakes — double-check important information.</p>
          </footer>
        )}
          </div>
        </div>
        )}
      </div>

      {openDoc && <ArtifactPanel doc={openDoc} onClose={closeArtifact} />}

      {!openDoc && showInfo && view !== "cowork" && (
        <InfoPanel
          artifacts={artifacts}
          projectName={proj.active ? activeProjectName : null}
          files={projDetail.files}
          onOpenArtifact={openArtifact}
          onManageProject={() => setShowProject(true)}
          onClose={() => setShowInfo(false)}
        />
      )}

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
                run: () => void openFromRecents(h.id, h.project_id ?? "general"),
              }));
          }}
          onClose={() => setShowPalette(false)}
        />
      )}

      {settingsPage && (
        <SettingsModal
          page={settingsPage}
          onPage={setSettingsPage}
          onClose={() => setSettingsPage(null)}
          active={{ provider: defaults.provider, model: defaults.model }}
          onPick={(p, m) => {
            // Settings picks the workspace default; also apply to the live conversation.
            setDefaults((d) => ({ ...d, provider: p, model: m }));
            applyOptions({ provider: p, model: m });
          }}
          skills={skills}
          conn={{
            servers: connectors.servers,
            enabled: connectors.enabled,
            err: connectors.err,
            onAdd: (body) => void connectors.add(body),
            onAddDemo: () => void connectors.addDemo(),
            onInstall: (file) => void connectors.install(file),
            onAddOAuth: (name, url) => void connectors.addOAuth(name, url),
            onAuthorize: (sid) => void connectors.authorize(sid),
            onRemove: (sid) => void connectors.remove(sid),
            onToggle: connectors.toggle,
          }}
          plug={{
            installed: pluginMgr.installed,
            market: pluginMgr.market,
            enabled: pluginMgr.enabled,
            err: pluginMgr.err,
            busy: pluginMgr.busy,
            onToggle: pluginMgr.toggle,
            onInstall: (name) => void pluginMgr.install(name),
            onUninstall: (name) => void pluginMgr.uninstall(name),
          }}
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
