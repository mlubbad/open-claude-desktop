import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { conversations, restoreCheckpoint, settings as settingsApi, workspaces } from "./api/client";
import { notify, onTrayNewChat, registerSummonHotkey, setCloseToTray, unregisterSummonHotkey } from "./platform";
import { loadDesktopPrefs, onDesktopPrefsChange } from "./state/desktopPrefs";
import { ApprovalPrompt } from "./components/ApprovalPrompt";
import { ArtifactPanel } from "./components/ArtifactPanel";
import { ChatMenu } from "./components/ChatMenu";
import { CreateProjectModal } from "./components/CreateProjectModal";
import { EditDetailsModal } from "./components/EditDetailsModal";
import { FeedbackModal } from "./components/FeedbackModal";
import { ProjectHome } from "./components/ProjectHome";
import { ProjectsPage } from "./components/ProjectsPage";
import { SetInstructionsModal } from "./components/SetInstructionsModal";
import { CodePanel } from "./components/CodePanel";
import { CoworkPanel } from "./components/CoworkPanel";
import { type Command, CommandPalette } from "./components/CommandPalette";
import {
  type AddMenuInfo,
  Composer,
  type ModelControlInfo,
  type WorkspaceControlInfo,
} from "./components/Composer";
import type { VoiceInfo } from "./components/MicPicker";
import { Icon } from "./components/Icon";
import { InfoPanel } from "./components/InfoPanel";
import { BackendBanner } from "./components/BackendBanner";
import { BranchBar } from "./components/BranchBar";
import { AssistantBubble, UserBubble } from "./components/Message";
import { ProjectPanel } from "./components/ProjectPanel";
import { SettingsModal, type SettingsPage } from "./components/SettingsModal";
import { ShortcutsHelp } from "./components/ShortcutsHelp";
import { Sidebar } from "./components/Sidebar";
import { UsageMeter } from "./components/UsageMeter";
import type { WorkspaceMode } from "./components/WorkspaceBar";
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
import { useBranchFamily } from "./state/useBranchFamily";
import { useConversations } from "./state/useConversations";
import { useKeyboard } from "./state/useKeyboard";
import { useMcpPrompts } from "./state/useMcpPrompts";
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
  // Incognito chat (P1-5): the conversation is never persisted — no history row, no
  // save, no auto-title. Exited by starting a normal chat or opening a saved one.
  const [incognito, setIncognito] = useState(false);
  // HITL autonomy (set in Settings): "strict" asks before every step, "ask" only before
  // sensitive actions (default), "auto" runs autonomously. Plan mode overrides it.
  const [approvalMode, setApprovalMode] = useState("ask");
  // Harness: the code workspace (folder) attached to the chat, if any. Attaching hands
  // permission-mode control to the WorkspaceBar's own selector (see `config` below) —
  // there's no native folder-picker plugin yet (that's a Tauri shell change, out of
  // scope here), so attach is a bare path prompt for now; swapping in a real dialog
  // later only touches attachWorkspace, not the harness components themselves.
  const [workspace, setWorkspace] = useState<{ id: string; root: string; mode: WorkspaceMode } | null>(null);
  // Projects is a full-page destination (list + per-project home), distinct from the
  // chat/code/cowork surface tabs. `projectsScreen` shows it; `projectDetail` is the
  // open project's id (null = the grid). Edit-details / instructions modals hang off it.
  const [projectsScreen, setProjectsScreen] = useState(false);
  const [projectDetail, setProjectDetail] = useState<string | null>(null);
  const [editDetailsFor, setEditDetailsFor] = useState<string | null>(null);
  const [showInstructions, setShowInstructions] = useState(false);
  // The conversation info rail (artifacts + project knowledge), toggled from the top bar.
  const [showInfo, setShowInfo] = useState(false);
  const [showCreateProject, setShowCreateProject] = useState(false);
  // Negative-feedback modal, opened from a reply's thumbs-down (local-only in BYOK).
  const [feedbackFor, setFeedbackFor] = useState<string | null>(null);

  const proj = useProjects();
  const connectors = useConnectors();
  const mcpPrompts = useMcpPrompts(connectors.servers, connectors.enabled);
  const pluginMgr = usePlugins();
  const skillsMgr = useSkills();
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

  // Attach a folder as a harness code workspace. No native folder-picker plugin is wired
  // up yet (Tauri dialog is a shell change, out of scope for the harness UI itself), so
  // this is a bare path prompt for now — functional, if unpolished; a real dialog can
  // replace just this handler later. Mirrors the window.prompt affordance already used
  // for project text notes (see onAddText below).
  const attachWorkspace = useCallback(async () => {
    const path = window.prompt("Folder path to attach as a code workspace:");
    if (!path?.trim()) return;
    try {
      const ws = await workspaces.create(path.trim());
      setWorkspace({ id: ws.id, root: ws.root, mode: "default" });
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "Couldn't attach that folder.");
    }
  }, []);

  const workspaceControl: WorkspaceControlInfo = useMemo(
    () => ({
      current: workspace ? { root: workspace.root, mode: workspace.mode } : null,
      onAttach: () => void attachWorkspace(),
      onModeChange: (mode) => setWorkspace((w) => (w ? { ...w, mode } : w)),
      onDetach: () => setWorkspace(null),
    }),
    [workspace, attachWorkspace],
  );

  const config = useMemo(
    () => ({
      provider: active.provider,
      model: active.model,
      effort: active.effort,
      style: active.style,
      // Attaching a workspace hands permission-mode control to its own selector (the
      // harness modes: default/acceptEdits/plan/strict/bypass) — it supersedes the plain
      // chat-level plan toggle / HITL autonomy setting while attached.
      permissionMode: workspace ? workspace.mode : planMode ? "plan" : approvalMode,
      projectId: proj.active,
      workspaceId: workspace?.id ?? null,
      // Feed the turn the ACTIVE set (intent ∩ healthy), not raw intent, so an
      // erroring connector isn't reached for — while the user's choice is preserved.
      enabledMcp: connectors.active,
      enabledPlugins: pluginMgr.enabled,
      // Capability toggles: web search / research gate real tools; Code mode adds the
      // file + shell + subagent tools over the workspace.
      options: {
        web_search: active.webSearch,
        research: active.research,
        // Code execution can be turned on per-chat from the + menu; the Code tab also
        // brings the file + shell + subagent tools over the workspace.
        code_exec: active.codeExec || view === "code",
        ...(view === "code" ? { text_editor: true, bash: true, subagents: true } : {}),
      },
    }),
    [active, proj.active, connectors.active, pluginMgr.enabled, view, planMode, approvalMode, workspace],
  );
  const {
    state,
    busy,
    send,
    retryLast,
    editAndResend,
    stop,
    resolveApproval,
    answerQuestion,
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
    move,
    branchAt,
  } = useConversations(config, incognito);

  // A turn's workspace_id failed to resolve server-side (workspace_detached) — the
  // folder is gone/stale, so drop the local attachment too rather than keep sending a
  // dead id on every follow-up turn. The composer's own notice (state.workspaceDetached)
  // explains why to the user; this just stops repeating the mistake.
  useEffect(() => {
    if (state.workspaceDetached) setWorkspace(null);
  }, [state.workspaceDetached]);

  // Restore a workspace's files to their state before a given message (RewindMenu).
  // Undefined while nothing is attached — Message.tsx only renders the menu when both
  // a checkpoint AND this handler are present. Scoped to the CURRENTLY attached
  // workspace: a checkpoint from a since-detached/replaced workspace 404s server-side
  // (owned_by check) rather than silently restoring the wrong folder.
  const restoreCheckpointFor = workspace
    ? (turnId: string, what: "files") => {
        void restoreCheckpoint(workspace.id, turnId, what).catch((e) => {
          window.alert(e instanceof Error ? e.message : "Couldn't restore that checkpoint.");
        });
      }
    : undefined;

  // The branch family (tree) of the open conversation, powering the transcript's branch
  // switcher. Incognito chats never persist, so they can't branch — skip the fetch.
  const family = useBranchFamily(current, !incognito);
  // Branching forks the persisted transcript at a visible message index; that index maps
  // 1:1 to the stored one only when nothing is streaming, so offer it just when idle on a
  // real (saved, non-incognito) conversation.
  const canBranch = !!current && !incognito && !busy;

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
        setApprovalMode(s.permission_mode ?? "ask");
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

  // Refresh the autonomy mode whenever the Settings modal closes, so a change there
  // takes effect on the next turn without a reload.
  useEffect(() => {
    if (settingsPage !== null) return;
    settingsApi.get().then((s) => setApprovalMode(s.permission_mode ?? "ask")).catch(() => {});
  }, [settingsPage]);

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
        setIncognito(false); // a saved chat is by definition not incognito
      }
      setProjectsScreen(false); // opening a chat leaves the Projects screen
    },
    [openConversation, setActiveProject],
  );

  // The open project's home data (instructions / memory / knowledge files).
  const homeDetail = useProjectDetail(projectDetail);
  const detailProject = proj.list.find((p) => p.id === projectDetail) ?? null;

  // Open the Projects grid.
  const openProjectsPage = useCallback(() => {
    setProjectDetail(null);
    setProjectsScreen(true);
  }, []);
  // Open a project's home (scopes new chats to it). Resets the transcript so a message
  // sent from the project composer starts a fresh conversation inside the project.
  const openProject = useCallback(
    (pid: string) => {
      setActiveProject(pid);
      newChat();
      setProjectDetail(pid);
      setProjectsScreen(true);
    },
    [setActiveProject, newChat],
  );
  // Sending from the project home reveals the chat surface with the streaming reply.
  const sendFromProject = useCallback(
    (text: string, images?: string[]) => {
      setProjectsScreen(false);
      void send(text, images);
    },
    [send],
  );
  // New chat / surface switches leave the Projects screen and show the chat surface. The
  // top-level "New chat" is always a General (no-project) chat — starting a chat inside a
  // project happens from that project's home instead.
  const goNewChat = useCallback(() => {
    setProjectsScreen(false);
    setActiveProject(null);
    setIncognito(false);
    newChat();
  }, [newChat, setActiveProject]);
  // An incognito chat: same fresh-draft flow, but nothing about it will persist.
  const goNewIncognito = useCallback(() => {
    setProjectsScreen(false);
    setActiveProject(null);
    setIncognito(true);
    newChat();
  }, [newChat, setActiveProject]);
  const goView = useCallback((v: "chat" | "code" | "cowork") => {
    setProjectsScreen(false);
    setView(v);
  }, []);

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
    onNewChat: goNewChat,
    onPalette: () => setShowPalette(true),
    onHelp: () => setShowHelp(true),
  });

  const commands: Command[] = useMemo(() => {
    const actions: Command[] = [
      { label: "New chat", hint: "⌘⇧O", run: goNewChat },
      { label: "New incognito chat", hint: "not saved to history", run: goNewIncognito },
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
  }, [goNewChat, goNewIncognito, proj.active, list, openFromRecents]);

  // Global summon hotkey (desktop only; no-op on web). Fired from the OS even when the
  // app is unfocused; brings it forward and starts a fresh chat. The Desktop-app
  // Settings switch drives it live via the desktop-prefs change event (P1-9).
  const newChatRef = useRef(goNewChat);
  newChatRef.current = goNewChat;
  useEffect(() => {
    const accel = "CmdOrControl+Shift+Space";
    let registered = false;
    const apply = (on: boolean) => {
      if (on === registered) return;
      registered = on;
      if (on) void registerSummonHotkey(accel, () => newChatRef.current());
      else void unregisterSummonHotkey(accel);
    };
    apply(loadDesktopPrefs().summonHotkey);
    const unlisten = onDesktopPrefsChange((p) => apply(p.summonHotkey));
    return () => {
      unlisten();
      apply(false);
    };
  }, []);

  // Close-to-tray (desktop only): tell the shell once on startup what the persisted
  // pref is, then keep it in sync with the Settings switch (P1-9).
  useEffect(() => {
    void setCloseToTray(loadDesktopPrefs().closeToTray);
    return onDesktopPrefsChange((p) => void setCloseToTray(p.closeToTray));
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
    projects: proj.list.map((p) => ({ id: p.id, name: p.name })),
    activeProjectId: proj.active,
    // File this conversation under the picked project (null = General). A saved chat is
    // moved server-side (move() keeps current.pid + Recents in sync); an unsaved one just
    // sets the context so its first message lands in that project.
    onPickProject: (id) => {
      const dstPid = id ?? "general";
      if (current?.cid && current.pid !== dstPid) void move(current.cid, current.pid, dstPid);
      setActiveProject(id);
    },
    onCreateProject: () => setShowCreateProject(true),
    onAddFromGitHub: () => setSettingsPage("connectors"),
    openSkills: () => setSettingsPage("skills"),
    connectors: connectors.servers.map((s) => ({ id: s.id, name: s.name, status: s.status })),
    enabledConnectors: connectors.enabled,
    onToggleConnector: connectors.toggle,
    openConnectors: () => setSettingsPage("connectors"),
    pluginsList: pluginMgr.installed.map((p) => ({ name: p.name, description: p.description })),
    enabledPlugins: pluginMgr.enabled,
    onTogglePlugin: pluginMgr.toggle,
    openPlugins: () => setSettingsPage("plugins"),
    openMarketplace: () => setSettingsPage("plugins"),
    research: active.research,
    onResearch: (on) => applyOptions({ research: on }),
    webSearch: active.webSearch,
    onWebSearch: (on) => applyOptions({ webSearch: on }),
    codeExec: active.codeExec,
    onCodeExec: (on) => applyOptions({ codeExec: on }),
    style: active.style,
    onStyle: (style) => applyOptions({ style }),
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

  // Create-project modal (name + description). Stores the description and opens the new
  // project's home so the user can add context and start a chat there.
  async function createProjectWithGoal(name: string, description: string) {
    const id = await proj.create(name.trim(), description.trim());
    setShowCreateProject(false);
    if (id) openProject(id);
  }

  const convTitle = list.find((c) => c.id === current?.cid)?.title;

  return (
    <div className="app-shell">
      <BackendBanner />
      <Sidebar
        view={view}
        onView={goView}
        projects={proj.list}
        activeProject={proj.active}
        projectsActive={projectsScreen}
        onProjects={openProjectsPage}
        onOpenProject={openProject}
        onArtifacts={() => setShowInfo(true)}
        list={list}
        currentId={current?.cid ?? null}
        err={histErr ?? proj.err}
        onNew={goNewChat}
        onOpen={openFromRecents}
        onDelete={remove}
        onRename={rename}
        onTogglePin={togglePin}
        onMove={move}
        onCustomize={() => setSettingsPage("general")}
        modelLabel={`${defaults.provider} · ${defaults.model}`}
        userName={profileName}
      />

      <div className="app">
        <header className="topbar">
          <div className="topbar-crumbs">
            {projectsScreen ? (
              <span className="crumb-title-static">Projects</span>
            ) : (
              <>
                {proj.active && view !== "cowork" && (
                  <>
                    <button className="crumb-proj" title="Open project" onClick={() => proj.active && openProject(proj.active)}>
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
              </>
            )}
          </div>
          <div className="topbar-right">
            {view !== "cowork" && !projectsScreen && (
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
            {view !== "cowork" && !projectsScreen && (
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

        {incognito && !projectsScreen && view === "chat" && (
          <div className="incognito-banner" role="status">
            <Icon name="eye-off" size={14} />
            Incognito chat — this conversation won't be saved to your history.
          </div>
        )}

        {projectsScreen && projectDetail && detailProject ? (
          <ProjectHome
            project={detailProject}
            instructions={homeDetail.instructions}
            memory={homeDetail.memory}
            memoryUpdated={homeDetail.memoryUpdated}
            files={homeDetail.files}
            composer={
              <Composer
                busy={busy}
                onSend={sendFromProject}
                onStop={stop}
                skills={skillsMgr.list}
                mcpPrompts={mcpPrompts}
                draftKey={`project-${projectDetail}`}
                placeholder="How can I help with this project?"
                addMenu={addMenu}
                modelControl={modelControl}
                voice={voice}
                workspace={workspaceControl}
                workspaceDetached={state.workspaceDetached}
              />
            }
            onBack={openProjectsPage}
            onEditInstructions={() => setShowInstructions(true)}
            onUploadFile={(f) => void homeDetail.upload(f)}
            onAddText={() => {
              const text = window.prompt("Paste text to add as project context:");
              if (text && text.trim()) {
                const name = window.prompt("File name:", "note.txt") || "note.txt";
                void homeDetail.addText(name, text);
              }
            }}
            onRemoveFile={(name) => void homeDetail.removeFile(name)}
            onEditDetails={() => setEditDetailsFor(projectDetail)}
            onTogglePin={() => void proj.update(projectDetail, { pinned: !detailProject.pinned })}
            onArchive={() => { void proj.update(projectDetail, { archived: true }); openProjectsPage(); }}
            onDelete={() => { void proj.remove(projectDetail); openProjectsPage(); }}
          />
        ) : projectsScreen ? (
          <ProjectsPage
            list={proj.list}
            onOpen={openProject}
            onNew={() => setShowCreateProject(true)}
            onEditDetails={(pid) => setEditDetailsFor(pid)}
            onTogglePin={(pid, pinned) => void proj.update(pid, { pinned })}
            onArchive={(pid) => void proj.update(pid, { archived: true })}
            onDelete={(pid) => void proj.remove(pid)}
          />
        ) : view === "cowork" ? (
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
            onClear={cowork.clear}
            onResolveApproval={cowork.resolveApproval}
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
                  skills={skillsMgr.list}
                mcpPrompts={mcpPrompts}
                  draftKey={current?.cid ?? "new"}
                  initialText={getDraft(drafts, current?.cid ?? "new")}
                  onTextChange={(t) => setDrafts((d) => setDraft(d, current?.cid ?? "new", t))}
                  placeholder="How can I help you today?"
                  addMenu={addMenu}
                  modelControl={modelControl}
                  voice={voice}
                  modeToggle={{ mode: "chat", onMode: (m) => m === "cowork" && goView("cowork") }}
                  workspace={workspaceControl}
                  workspaceDetached={state.workspaceDetached}
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
          {family && family.nodes.length > 1 && (
            <BranchBar family={family} current={current?.cid ?? null} onSwitch={openFromRecents} />
          )}
          {state.messages.map((m, i) =>
            m.role === "user" ? (
              <UserBubble
                key={`${current?.cid ?? "new"}-${i}`}
                msg={m}
                onEdit={busy ? undefined : (text) => editAndResend(i, text)}
                // Branching only makes sense on a saved conversation, and the visible
                // index maps 1:1 to the persisted transcript only when nothing is
                // streaming — so offer it just when idle on a real (non-incognito) chat.
                onBranch={canBranch ? () => void branchAt(i) : undefined}
              />
            ) : (
              // Keyed per conversation so per-message local state (feedback votes,
              // edit drafts) never leaks across chat switches.
              <AssistantBubble
                key={`${current?.cid ?? "new"}-${i}`}
                msg={m}
                isLast={i === lastAssistantIdx}
                busy={busy}
                onRetry={() => retryLast()}
                // Regenerate with a different model: run this turn on the picked
                // model AND switch the conversation forward to it (the composer
                // then reflects it and follow-ups continue there).
                onRetryWith={(p, mdl) => {
                  applyOptions({ provider: p, model: mdl });
                  retryLast({ provider: p, model: mdl });
                }}
                retryProvider={active.provider}
                retryModel={active.model}
                onOpenArtifact={openArtifact}
                onAnswerQuestion={answerQuestion}
                onFeedback={() => setFeedbackFor(current?.cid ?? "new")}
                onBranch={canBranch ? () => void branchAt(i) : undefined}
                onRestoreCheckpoint={restoreCheckpointFor}
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
          {/* Sentinel at the very end of the transcript: the jump-to-latest button shows
              exactly when this is off-screen (see useAutoScroll). */}
          <div ref={scroll.bottomRef} className="scroll-sentinel" aria-hidden="true" />
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
              skills={skillsMgr.list}
                mcpPrompts={mcpPrompts}
              draftKey={current?.cid ?? "new"}
              initialText={getDraft(drafts, current?.cid ?? "new")}
              onTextChange={(t) => setDrafts((d) => setDraft(d, current?.cid ?? "new", t))}
              addMenu={addMenu}
              modelControl={modelControl}
              voice={voice}
              modeToggle={{ mode: "chat", onMode: (m) => m === "cowork" && goView("cowork") }}
              workspace={workspaceControl}
              workspaceDetached={state.workspaceDetached}
            />
            <p className="footer-note">AI can make mistakes — double-check important information.</p>
          </footer>
        )}
          </div>
        </div>
        )}
      </div>

      {openDoc && (
        <ArtifactPanel
          doc={openDoc}
          onClose={closeArtifact}
          projectId={proj.active}
          projectName={proj.active ? activeProjectName : null}
          onAdded={() => void projDetail.reload()}
        />
      )}

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

      {showCreateProject && (
        <CreateProjectModal
          onCreate={(name, goal) => void createProjectWithGoal(name, goal)}
          onClose={() => setShowCreateProject(false)}
        />
      )}

      {editDetailsFor && (() => {
        const p = proj.list.find((x) => x.id === editDetailsFor);
        if (!p) return null;
        return (
          <EditDetailsModal
            initialName={p.name}
            initialDescription={p.description ?? ""}
            onSave={(name, description) => {
              void proj.update(editDetailsFor, { name, description });
              setEditDetailsFor(null);
            }}
            onClose={() => setEditDetailsFor(null)}
          />
        );
      })()}

      {showInstructions && detailProject && (
        <SetInstructionsModal
          projectName={detailProject.name}
          initial={homeDetail.instructions}
          onSave={(text) => {
            void homeDetail.saveInstructions(text);
            setShowInstructions(false);
          }}
          onClose={() => setShowInstructions(false)}
        />
      )}

      {feedbackFor && (
        <FeedbackModal
          onSubmit={(issueType, details) => {
            // Local-only in a BYOK build: record to localStorage, nothing leaves the device.
            try {
              const log = JSON.parse(localStorage.getItem("ocd.feedback") ?? "[]");
              log.push({ cid: current?.cid ?? null, issueType, details });
              localStorage.setItem("ocd.feedback", JSON.stringify(log));
            } catch {
              /* ignore quota/parse */
            }
            setFeedbackFor(null);
          }}
          onClose={() => setFeedbackFor(null)}
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
          skills={{
            list: skillsMgr.list,
            busy: skillsMgr.busy,
            allowRemote: pluginMgr.allowRemote,
            importFile: skillsMgr.importFile,
            importZip: skillsMgr.importZip,
            importFromRepo: skillsMgr.importFromRepo,
            onRemove: (name) => void skillsMgr.remove(name),
          }}
          conn={{
            servers: connectors.servers,
            enabled: connectors.enabled,
            err: connectors.err,
            onAdd: (body) => void connectors.add(body),
            onInstall: (file) => void connectors.install(file),
            onAddOAuth: (name, url) => void connectors.addOAuth(name, url),
            onAuthorize: (sid) => void connectors.authorize(sid),
            onRemove: (sid) => void connectors.remove(sid),
            onToggle: connectors.toggle,
            onRetry: (sid) => void connectors.retry(sid),
            retrying: connectors.retrying,
            onToolToggle: (sid, tool, enabled) => void connectors.setToolEnabled(sid, tool, enabled),
            updates: connectors.updates,
            updating: connectors.updating,
            onCheckUpdate: (sid) => void connectors.checkUpdate(sid),
            onUpdate: (sid, values) => void connectors.applyUpdate(sid, values),
            updateNeeds: connectors.updateNeeds,
          }}
          plug={{
            installed: pluginMgr.installed,
            market: pluginMgr.market,
            sources: pluginMgr.sources,
            allowRemote: pluginMgr.allowRemote,
            enabled: pluginMgr.enabled,
            err: pluginMgr.err,
            busy: pluginMgr.busy,
            onToggle: pluginMgr.toggle,
            onInstall: (name) => void pluginMgr.install(name),
            onUninstall: (name) => void pluginMgr.uninstall(name),
            onAddSource: pluginMgr.addSource,
            onRemoveSource: (id) => void pluginMgr.removeSource(id),
          }}
          theme={{ pref: theme.pref, set: theme.set }}
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
