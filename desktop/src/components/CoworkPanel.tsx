import { useState } from "react";

import type { CoworkDetail, CoworkTask, Schedule } from "../api/client";
import { AssistantBubble, UserBubble } from "./Message";
import { replayEvents, statusBadge } from "../state/coworkView";

export interface SchedControls {
  items: Schedule[];
  err: string | null;
  add: (body: { goal: string; kind: "interval" | "daily"; every_seconds?: number; at?: string }) => void;
  remove: (id: string) => void;
  toggle: (id: string, enabled: boolean) => void;
}

// The Cowork tab: delegate a task the agent runs in the background, schedule recurring
// tasks, watch the task list, and inspect any task's transcript (replayed through the
// shared transcript reducer).
export function CoworkPanel({
  tasks,
  selected,
  err,
  sched,
  onStart,
  onOpen,
  onCancel,
}: {
  tasks: CoworkTask[];
  selected: CoworkDetail | null;
  err: string | null;
  sched: SchedControls;
  onStart: (goal: string) => void;
  onOpen: (id: string) => void;
  onCancel: (id: string) => void;
}) {
  const [goal, setGoal] = useState("");

  function delegate() {
    if (!goal.trim()) return;
    onStart(goal);
    setGoal("");
  }

  return (
    <div className="cowork">
      <div className="cowork-list">
        <div className="cowork-delegate">
          <textarea
            placeholder="Delegate a task — the agent works on it in the background…"
            value={goal}
            rows={3}
            onChange={(e) => setGoal(e.target.value)}
          />
          <button className="conn-submit" disabled={!goal.trim()} onClick={delegate}>
            Delegate task
          </button>
        </div>
        {err && <div className="settings-err">{err}</div>}

        <ScheduleSection sched={sched} />

        <div className="cowork-tasks">
          {tasks.length === 0 && <div className="code-empty">No background tasks yet.</div>}
          {tasks.map((t) => {
            const b = statusBadge(t.status);
            return (
              <div
                key={t.id}
                className={`cowork-task ${selected?.id === t.id ? "active" : ""}`}
                onClick={() => onOpen(t.id)}
              >
                <span className={`cowork-status ${b.cls}`} title={b.label}>{b.icon}</span>
                <span className="cowork-title" title={t.title}>{t.title}</span>
                {t.status === "running" && (
                  <button
                    className="conn-del"
                    title="Cancel"
                    onClick={(e) => {
                      e.stopPropagation();
                      onCancel(t.id);
                    }}
                  >
                    ✕
                  </button>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="cowork-detail">
        {selected ? (
          <TaskTranscript detail={selected} />
        ) : (
          <div className="code-empty">Select a task to see its progress.</div>
        )}
      </div>
    </div>
  );
}

function ScheduleSection({ sched }: { sched: SchedControls }) {
  const [open, setOpen] = useState(false);
  const [goal, setGoal] = useState("");
  const [kind, setKind] = useState<"interval" | "daily">("interval");
  const [everyMin, setEveryMin] = useState("60");
  const [at, setAt] = useState("09:00");

  function submit() {
    if (!goal.trim()) return;
    if (kind === "interval") {
      const mins = Math.max(1, parseInt(everyMin, 10) || 0);
      sched.add({ goal, kind, every_seconds: mins * 60 });
    } else {
      sched.add({ goal, kind, at });
    }
    setGoal("");
  }

  return (
    <div className="cowork-sched">
      <button className="cowork-sched-head" onClick={() => setOpen((o) => !o)}>
        <span>⏰ Scheduled</span>
        <span className="cowork-sched-count">{sched.items.length}</span>
        <span className="cowork-sched-caret">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <div className="cowork-sched-body">
          {sched.err && <div className="settings-err">{sched.err}</div>}
          <input
            className="cowork-sched-goal"
            placeholder="Goal to run on a schedule…"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
          <div className="cowork-sched-when">
            <select value={kind} onChange={(e) => setKind(e.target.value as "interval" | "daily")}>
              <option value="interval">Every</option>
              <option value="daily">Daily at</option>
            </select>
            {kind === "interval" ? (
              <>
                <input
                  type="number"
                  min={1}
                  className="cowork-sched-num"
                  value={everyMin}
                  onChange={(e) => setEveryMin(e.target.value)}
                />
                <span className="cowork-sched-unit">min</span>
              </>
            ) : (
              <input
                type="time"
                value={at}
                onChange={(e) => setAt(e.target.value)}
              />
            )}
            <button className="conn-submit" disabled={!goal.trim()} onClick={submit}>
              Add
            </button>
          </div>

          {sched.items.map((s) => (
            <div key={s.id} className={`cowork-sched-item ${s.enabled ? "" : "off"}`}>
              <input
                type="checkbox"
                checked={s.enabled}
                title={s.enabled ? "Enabled" : "Disabled"}
                onChange={() => sched.toggle(s.id, !s.enabled)}
              />
              <span className="cowork-sched-title" title={s.goal}>{s.title}</span>
              <span className="cowork-sched-cadence">{s.cadence}</span>
              <button className="conn-del" title="Delete" onClick={() => sched.remove(s.id)}>
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TaskTranscript({ detail }: { detail: CoworkDetail }) {
  const state = replayEvents(detail.goal, detail.event_list);
  const lastAssistant = state.messages.reduce((acc, m, i) => (m.role === "assistant" ? i : acc), -1);
  const b = statusBadge(detail.status);
  return (
    <div className="cowork-transcript">
      <div className="cowork-detail-head">
        <span className={`cowork-status ${b.cls}`}>{b.icon}</span> {b.label}
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
