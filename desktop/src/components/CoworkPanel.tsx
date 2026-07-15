import { useRef, useState } from "react";

import type { CoworkDetail, CoworkTask, Schedule } from "../api/client";
import { AssistantBubble, UserBubble } from "./Message";
import { nextRun, nextRunLabel, relativeTime, replayEvents, statusBadge } from "../state/coworkView";
import { useMenuFit } from "../state/useMenuFit";
import { Icon } from "./Icon";

export interface SchedControls {
  items: Schedule[];
  err: string | null;
  add: (body: { goal: string; kind: "interval" | "daily"; every_seconds?: number; at?: string }) => void;
  remove: (id: string) => void;
  toggle: (id: string, enabled: boolean) => void;
}

const APPROVALS = [
  { value: "manual", label: "Manual", desc: "Claude pauses so you can approve each action." },
  { value: "skip", label: "Skip", desc: "Claude never pauses, even for unsafe actions." },
] as const;

// The Cowork surface. Home = a composer-forward hero (delegate a goal, with a
// Manual/Skip approvals pill), the Active task list (status dot + relative time +
// Review, with Clear active + Show more), and the Scheduled automations list showing
// each next run. Review opens the task transcript with a right rail (Progress /
// Workspace files / Context) and, for a Manual task paused for approval, Approve/Decline.
export function CoworkPanel({
  tasks,
  selected,
  err,
  sched,
  projectName,
  onStart,
  onOpen,
  onBack,
  onCancel,
  onClear,
  onResolveApproval,
}: {
  tasks: CoworkTask[];
  selected: CoworkDetail | null;
  err: string | null;
  sched: SchedControls;
  projectName: string;
  onStart: (goal: string, approval: "skip" | "manual") => void;
  onOpen: (id: string) => void;
  onBack: () => void;
  onCancel: (id: string) => void;
  onClear: () => void;
  onResolveApproval: (turnId: string, toolCallId: string, decision: "approve" | "decline") => void;
}) {
  if (selected) {
    return <ReviewView detail={selected} onBack={onBack} onCancel={onCancel} onResolveApproval={onResolveApproval} />;
  }
  return (
    <CoworkHome
      tasks={tasks}
      err={err}
      sched={sched}
      projectName={projectName}
      onStart={onStart}
      onOpen={onOpen}
      onCancel={onCancel}
      onClear={onClear}
    />
  );
}

function CoworkHome({
  tasks,
  err,
  sched,
  projectName,
  onStart,
  onOpen,
  onCancel,
  onClear,
}: {
  tasks: CoworkTask[];
  err: string | null;
  sched: SchedControls;
  projectName: string;
  onStart: (goal: string, approval: "skip" | "manual") => void;
  onOpen: (id: string) => void;
  onCancel: (id: string) => void;
  onClear: () => void;
}) {
  const [goal, setGoal] = useState("");
  const [approval, setApproval] = useState<"skip" | "manual">("manual");
  const [apprOpen, setApprOpen] = useState(false);
  const apprRef = useRef<HTMLDivElement>(null);
  useMenuFit(apprRef, apprOpen);
  const [showSchedForm, setShowSchedForm] = useState(false);
  const [showAll, setShowAll] = useState(false);

  const visible = showAll ? tasks : tasks.slice(0, 5);

  function delegate() {
    if (!goal.trim()) return;
    onStart(goal, approval);
    setGoal("");
  }

  return (
    <div className="cw-home">
      <div className="cw-col">
        <h1 className="cw-hero">
          <span className="hero-mark" aria-hidden="true" />
          Let’s tackle something together
        </h1>
        <p className="cw-sub">
          Give Claude a task (or a few) to run autonomously in the background.
        </p>

        <div className="composer cw-composer">
          <textarea
            placeholder="What should we work on?"
            value={goal}
            rows={2}
            onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                delegate();
              }
            }}
          />
          <div className="composer-row">
            <span className="composer-pill" title="This task runs inside this project">
              <Icon name="folder" size={13} /> {projectName}
            </span>
            <div className="cw-appr-anchor">
              <button
                className="composer-pill"
                aria-haspopup="menu"
                aria-expanded={apprOpen}
                title="Approvals for this task"
                onClick={() => setApprOpen((v) => !v)}
              >
                <Icon name="shield" size={13} /> {APPROVALS.find((a) => a.value === approval)?.label}
                <Icon name="chev-down" size={11} />
              </button>
              {apprOpen && (
                <div className="cw-appr-menu" role="menu" aria-label="Approvals" ref={apprRef}>
                  {APPROVALS.map((a) => (
                    <button
                      key={a.value}
                      role="menuitemradio"
                      aria-checked={approval === a.value}
                      onClick={() => { setApproval(a.value); setApprOpen(false); }}
                    >
                      <span className="cw-appr-label">
                        {a.label}
                        {approval === a.value && <Icon name="check" size={13} />}
                      </span>
                      <span className="cw-appr-desc">{a.desc}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <span className="composer-spacer" />
            <button className="composer-send" title="Delegate" aria-label="Delegate" disabled={!goal.trim()} onClick={delegate}>
              <Icon name="arrow-up" size={17} />
            </button>
          </div>
        </div>
        {err && <div className="settings-err">{err}</div>}

        <section className="cw-section">
          <div className="cw-section-row">
            <h3 className="cw-section-head">Active</h3>
            {tasks.some((t) => t.status !== "running") && (
              <button className="cw-add" onClick={onClear}>Clear active</button>
            )}
          </div>
          {tasks.length === 0 && <div className="cw-empty">No background tasks yet.</div>}
          {visible.map((t) => {
            const b = statusBadge(t.status);
            return (
              <button key={t.id} className="cw-row cw-row-btn" onClick={() => onOpen(t.id)}>
                <span className={`cowork-status ${b.cls}`} title={b.label} aria-label={b.label}>
                  ●
                </span>
                <span className="cw-row-main">
                  <span className="cw-row-title" title={t.title}>{t.title}</span>
                  <span className="cw-row-meta">
                    {relativeTime(t.updated_at)}
                    {t.approval === "manual" && " · manual"}
                  </span>
                </span>
                {t.status === "running" && (
                  <span
                    className="cw-cancel"
                    role="button"
                    tabIndex={0}
                    title="Cancel task"
                    aria-label={`Cancel ${t.title}`}
                    onClick={(e) => { e.stopPropagation(); onCancel(t.id); }}
                  >
                    <Icon name="x" size={13} />
                  </span>
                )}
              </button>
            );
          })}
          {tasks.length > 5 && (
            <button className="cw-showmore" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show less" : `Show more (${tasks.length - 5})`}
            </button>
          )}
        </section>

        <section className="cw-section">
          <div className="cw-section-row">
            <h3 className="cw-section-head">Scheduled</h3>
            <button className="cw-add" onClick={() => setShowSchedForm((v) => !v)}>
              {showSchedForm ? "Cancel" : "＋ New schedule"}
            </button>
          </div>
          {showSchedForm && (
            <ScheduleForm
              onAdd={(body) => {
                sched.add(body);
                setShowSchedForm(false);
              }}
            />
          )}
          {sched.err && <div className="settings-err">{sched.err}</div>}
          {sched.items.length === 0 && !showSchedForm && (
            <div className="cw-empty">No scheduled tasks — automate a recurring goal.</div>
          )}
          {sched.items.map((s) => (
            <div key={s.id} className={`cw-row ${s.enabled ? "" : "off"}`}>
              <span className="cw-clock" aria-hidden="true"><Icon name="clock" size={15} /></span>
              <span className="cw-row-main">
                <span className="cw-row-title" title={s.goal}>{s.title}</span>
                <span className="cw-row-meta">
                  {s.cadence} · {s.enabled ? nextRunLabel(nextRun(s)) : "paused"}
                </span>
              </span>
              <input
                type="checkbox"
                checked={s.enabled}
                aria-label={`Enable schedule: ${s.title}`}
                onChange={() => sched.toggle(s.id, !s.enabled)}
              />
              <button
                className="cw-cancel"
                title="Delete schedule"
                aria-label={`Delete schedule: ${s.title}`}
                onClick={() => sched.remove(s.id)}
              >
                <Icon name="x" size={13} />
              </button>
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}

function ScheduleForm({
  onAdd,
}: {
  onAdd: (body: { goal: string; kind: "interval" | "daily"; every_seconds?: number; at?: string }) => void;
}) {
  const [goal, setGoal] = useState("");
  const [kind, setKind] = useState<"interval" | "daily">("interval");
  const [everyMin, setEveryMin] = useState("60");
  const [at, setAt] = useState("09:00");

  function submit() {
    if (!goal.trim()) return;
    if (kind === "interval") {
      const mins = Math.max(1, parseInt(everyMin, 10) || 0);
      onAdd({ goal, kind, every_seconds: mins * 60 });
    } else {
      onAdd({ goal, kind, at });
    }
    setGoal("");
  }

  return (
    <div className="cw-sched-form">
      <input
        placeholder="Goal to run on a schedule…"
        aria-label="Schedule goal"
        value={goal}
        onChange={(e) => setGoal(e.target.value)}
      />
      <div className="cw-sched-when">
        <select value={kind} onChange={(e) => setKind(e.target.value as "interval" | "daily")} aria-label="Cadence">
          <option value="interval">Every</option>
          <option value="daily">Daily at</option>
        </select>
        {kind === "interval" ? (
          <>
            <input
              type="number"
              min={1}
              className="cw-sched-num"
              aria-label="Minutes"
              value={everyMin}
              onChange={(e) => setEveryMin(e.target.value)}
            />
            <span className="cw-sched-unit">min</span>
          </>
        ) : (
          <input type="time" aria-label="Time of day" value={at} onChange={(e) => setAt(e.target.value)} />
        )}
        <button className="conn-submit" disabled={!goal.trim()} onClick={submit}>
          Add
        </button>
      </div>
    </div>
  );
}

function ReviewView({
  detail,
  onBack,
  onCancel,
  onResolveApproval,
}: {
  detail: CoworkDetail;
  onBack: () => void;
  onCancel: (id: string) => void;
  onResolveApproval: (turnId: string, toolCallId: string, decision: "approve" | "decline") => void;
}) {
  const state = replayEvents(detail.goal, detail.event_list);
  const lastAssistant = state.messages.reduce((acc, m, i) => (m.role === "assistant" ? i : acc), -1);
  const b = statusBadge(detail.status);
  const pending = state.pendingApproval;
  return (
    <div className="cw-detail">
      <div className="cw-detail-main">
        <div className="cowork-detail-head">
          <button className="cw-back" onClick={onBack} aria-label="Back to Cowork">
            ← Back
          </button>
          <span className="cw-detail-title" title={detail.title}>{detail.title}</span>
          <span className={`cowork-status ${b.cls}`}>●</span> {b.label}
          {detail.status === "running" && (
            <button className="cw-cancel" title="Cancel task" onClick={() => onCancel(detail.id)}>
              Cancel
            </button>
          )}
          {detail.error && <span className="cowork-err"> — {detail.error}</span>}
        </div>
        <div className="transcript cowork-scroll">
          {state.messages.map((m, i) =>
            m.role === "user" ? (
              <UserBubble key={i} msg={m} />
            ) : (
              <AssistantBubble key={i} msg={m} isLast={i === lastAssistant} busy={false} />
            ),
          )}
          {/* Manual-mode task paused for approval: resolve it in place. */}
          {pending && detail.turn_id && detail.status === "running" && (
            <div className="cw-approval" role="alertdialog" aria-label="Approval required">
              <div className="cw-approval-body">
                <strong>Approval needed</strong> — {pending.name}
                {pending.input && <code className="cw-approval-input">{pending.input}</code>}
              </div>
              <div className="cw-approval-actions">
                <button onClick={() => onResolveApproval(detail.turn_id!, pending.toolCallId, "decline")}>
                  Decline
                </button>
                <button className="primary" onClick={() => onResolveApproval(detail.turn_id!, pending.toolCallId, "approve")}>
                  Approve
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <aside className="cw-rail" aria-label="Task details">
        <RailCard title="Progress" defaultOpen>
          <ProgressList steps={detail.progress} />
        </RailCard>
        <RailCard title="Workspace files" defaultOpen={detail.files.length > 0}>
          {detail.files.length === 0 ? (
            <p className="cw-rail-empty">No files produced yet.</p>
          ) : (
            <ul className="cw-rail-files">
              {detail.files.map((f) => (
                <li key={f.name}>
                  <Icon name="file" size={14} /> <span title={f.name}>{f.name}</span>
                </li>
              ))}
            </ul>
          )}
        </RailCard>
        <RailCard title="Context" defaultOpen>
          <p className="cw-rail-ctx">
            <Icon name="folder" size={14} /> {detail.project_id ?? "General"}
          </p>
          <p className="cw-rail-sub">
            Approvals: {detail.approval === "manual" ? "Manual" : "Skip"}
          </p>
        </RailCard>
      </aside>
    </div>
  );
}

type ProgressStep = { label: string; done: boolean };

function ProgressList({ steps }: { steps: ProgressStep[] }) {
  if (steps.length === 0) return <p className="cw-rail-empty">No steps recorded yet.</p>;
  return (
    <ul className="cw-progress">
      {steps.map((s, i) => (
        <li key={i} className={s.done ? "done" : "active"}>
          <span className="cw-progress-dot" aria-hidden="true">
            {s.done ? <Icon name="check" size={12} /> : i + 1}
          </span>
          <span className="cw-progress-label">{s.label}</span>
        </li>
      ))}
    </ul>
  );
}

function RailCard({ title, defaultOpen = false, children }: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="cw-rail-card">
      <button className="cw-rail-head" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        {title}
        <Icon name={open ? "chev-down" : "chev-right"} size={13} />
      </button>
      {open && <div className="cw-rail-body">{children}</div>}
    </div>
  );
}
