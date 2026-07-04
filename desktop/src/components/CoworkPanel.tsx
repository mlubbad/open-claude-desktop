import { useState } from "react";

import type { CoworkDetail, CoworkTask, Schedule } from "../api/client";
import { AssistantBubble, UserBubble } from "./Message";
import { replayEvents, statusBadge } from "../state/coworkView";
import { Icon } from "./Icon";

export interface SchedControls {
  items: Schedule[];
  err: string | null;
  add: (body: { goal: string; kind: "interval" | "daily"; every_seconds?: number; at?: string }) => void;
  remove: (id: string) => void;
  toggle: (id: string, enabled: boolean) => void;
}

// The Cowork surface. Home = a composer-forward hero (delegate a goal), the Active
// task list (status dot + meta + Review), and the Scheduled automations list.
// Clicking Review opens the task transcript full-width with a back affordance.
// All functions survive: delegate, cancel, replay transcript, schedules CRUD/toggle.
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
}: {
  tasks: CoworkTask[];
  selected: CoworkDetail | null;
  err: string | null;
  sched: SchedControls;
  projectName: string;
  onStart: (goal: string) => void;
  onOpen: (id: string) => void;
  onBack: () => void;
  onCancel: (id: string) => void;
}) {
  if (selected) {
    return <ReviewView detail={selected} onBack={onBack} onCancel={onCancel} />;
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
}: {
  tasks: CoworkTask[];
  err: string | null;
  sched: SchedControls;
  projectName: string;
  onStart: (goal: string) => void;
  onOpen: (id: string) => void;
  onCancel: (id: string) => void;
}) {
  const [goal, setGoal] = useState("");
  const [showSchedForm, setShowSchedForm] = useState(false);

  function delegate() {
    if (!goal.trim()) return;
    onStart(goal);
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
          Delegate a goal — the agent works on it autonomously in the background.
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
            <span className="composer-pill">Works in: {projectName}</span>
            <span className="composer-spacer" />
            <button className="composer-send" title="Delegate" disabled={!goal.trim()} onClick={delegate}>
              ↑
            </button>
          </div>
        </div>
        {err && <div className="settings-err">{err}</div>}

        <section className="cw-section">
          <h3 className="cw-section-head">Active</h3>
          {tasks.length === 0 && <div className="cw-empty">No background tasks yet.</div>}
          {tasks.map((t) => {
            const b = statusBadge(t.status);
            return (
              <div key={t.id} className="cw-row">
                <span className={`cowork-status ${b.cls}`} title={b.label} aria-label={b.label}>
                  ●
                </span>
                <span className="cw-row-main">
                  <span className="cw-row-title" title={t.title}>{t.title}</span>
                  <span className="cw-row-meta">
                    {b.label} · {t.events} events
                  </span>
                </span>
                {t.status === "running" && (
                  <button
                    className="cw-cancel"
                    title="Cancel task"
                    aria-label={`Cancel ${t.title}`}
                    onClick={() => onCancel(t.id)}
                  >
                    <Icon name="x" size={13} />
                  </button>
                )}
                <button className="cw-review" onClick={() => onOpen(t.id)}>
                  Review
                </button>
              </div>
            );
          })}
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
                <span className="cw-row-meta">{s.cadence}</span>
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
}: {
  detail: CoworkDetail;
  onBack: () => void;
  onCancel: (id: string) => void;
}) {
  const state = replayEvents(detail.goal, detail.event_list);
  const lastAssistant = state.messages.reduce((acc, m, i) => (m.role === "assistant" ? i : acc), -1);
  const b = statusBadge(detail.status);
  return (
    <div className="cowork-transcript">
      <div className="cowork-detail-head">
        <button className="cw-back" onClick={onBack} aria-label="Back to Cowork">
          ← Back
        </button>
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
      </div>
    </div>
  );
}
