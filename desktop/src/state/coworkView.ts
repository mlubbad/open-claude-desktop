// Pure helpers for the Cowork tab. Replays a completed/running task's stored event
// stream through the SAME transcript reducer the live chat uses, so a delegated task
// renders identically to an interactive one — no duplicate rendering logic.

import type { AgentEvent } from "../api/events";
import { applyEvent, initialState, startTurn, type TranscriptState } from "./transcript";

export function replayEvents(goal: string, events: AgentEvent[]): TranscriptState {
  let state = startTurn(initialState(), goal);
  for (const ev of events) state = applyEvent(state, ev);
  return state;
}

// A short status glyph + label for a task's state.
export function statusBadge(status: string): { icon: string; label: string; cls: string } {
  switch (status) {
    case "running":
      return { icon: "◐", label: "running", cls: "running" };
    case "done":
      return { icon: "✓", label: "done", cls: "done" };
    case "error":
      return { icon: "✗", label: "error", cls: "error" };
    case "cancelled":
      return { icon: "⊘", label: "cancelled", cls: "cancelled" };
    case "interrupted":
      return { icon: "⏸", label: "interrupted", cls: "error" };
    default:
      return { icon: "•", label: status, cls: "" };
  }
}

export function hasRunning(tasks: { status: string }[]): boolean {
  return tasks.some((t) => t.status === "running");
}

// A compact "2 minutes ago" / "yesterday" / "3 days ago" label from an ISO timestamp,
// matching the Cowork task rows in the reference. Pure (clock injected for tests).
export function relativeTime(iso: string, now: number = Date.now()): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const s = Math.max(0, Math.round((now - then) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`;
  const d = Math.round(h / 24);
  if (d === 1) return "yesterday";
  if (d < 30) return `${d} days ago`;
  const mo = Math.round(d / 30);
  return `${mo} month${mo === 1 ? "" : "s"} ago`;
}

// The next fire time of a schedule, as an absolute Date, given now — for the
// Scheduled list ("Tomorrow at 10:36 AM"). Interval schedules count from last_run
// (or now); daily schedules use the next HH:MM (UTC) occurrence. Pure + injectable.
export function nextRun(
  s: { kind: string; every_seconds?: number | null; at?: string | null; last_run?: string | null; enabled: boolean },
  now: number = Date.now(),
): Date | null {
  if (!s.enabled) return null;
  if (s.kind === "interval" && s.every_seconds && s.every_seconds > 0) {
    const base = s.last_run ? Date.parse(s.last_run) : now;
    const from = Number.isNaN(base) ? now : base;
    let next = from + s.every_seconds * 1000;
    if (next < now) next = now + s.every_seconds * 1000; // skip missed fires
    return new Date(next);
  }
  if (s.kind === "daily" && s.at) {
    const [hh, mm] = s.at.split(":").map((x) => parseInt(x, 10));
    if (Number.isNaN(hh) || Number.isNaN(mm)) return null;
    const d = new Date(now);
    d.setUTCHours(hh, mm, 0, 0);
    if (d.getTime() <= now) d.setUTCDate(d.getUTCDate() + 1);
    return d;
  }
  return null;
}

// Humanize a next-run Date relative to now: "Today at 4:05 PM" / "Tomorrow at …" /
// "Mon at …" / a full date for anything further out.
export function nextRunLabel(next: Date | null, now: number = Date.now()): string {
  if (!next) return "paused";
  const time = next.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const dayMs = 86_400_000;
  const startOfDay = (t: number) => { const d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime(); };
  const days = Math.round((startOfDay(next.getTime()) - startOfDay(now)) / dayMs);
  if (days <= 0) return `Today at ${time}`;
  if (days === 1) return `Tomorrow at ${time}`;
  if (days < 7) return `${next.toLocaleDateString(undefined, { weekday: "short" })} at ${time}`;
  return `${next.toLocaleDateString(undefined, { month: "short", day: "numeric" })} at ${time}`;
}
