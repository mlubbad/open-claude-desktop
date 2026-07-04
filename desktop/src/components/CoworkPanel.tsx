import { useState } from "react";

import type { CoworkDetail, CoworkTask } from "../api/client";
import { AssistantBubble, UserBubble } from "./Message";
import { replayEvents, statusBadge } from "../state/coworkView";

// The Cowork tab: delegate a task the agent runs in the background, watch the task list,
// and inspect any task's transcript (replayed through the shared transcript reducer).
export function CoworkPanel({
  tasks,
  selected,
  err,
  onStart,
  onOpen,
  onCancel,
}: {
  tasks: CoworkTask[];
  selected: CoworkDetail | null;
  err: string | null;
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
