# Claude-Desktop-style chat home at `/` — design

**Date:** 2026-06-30
**Status:** Approved (brainstorming) → ready to implement

## Problem

The app's first screen (`/`) is the **Projects grid**. The desired landing
(per the reference screenshot) is a Claude-Desktop **new-chat home**: a centered
time-of-day greeting, a centered composer ("How can I help you today?"), and a
row of quick-action chips. The sidebar already matches the reference.

## Approach (chosen)

Reuse the existing **General-chat** machinery. `/cowork`'s `workspace_composer()`
already targets `start_conversation` against the General space; present that as a
centered hero at `/`, and move the Projects grid to `/projects`.

## Components

### Routing — `aj360_app.py`
- `/` → new `home_page` (on_load `[require_login, load_home, check_backend]`)
- `/projects` → existing `dashboard` (moved off `/`)
- `/cowork` → redirect to `/` (General space now lives at the home; keeps links alive)

### Home page — new `components/home.py`
- `sidebar()` (unchanged) + a centered, vertically-centered column (~720px):
  - starburst mark + **greeting**: "Good evening, Mohammed" (word from server
    local hour; name = signed-in user, default "Mohammed")
  - the existing `workspace_composer()` (placeholder "How can I help you today?")
  - quick-action chips: **Query BigQuery · New project · Browse chats · Customize**

### State — `state.py`
- `load_home()` = `load_cowork()` behavior (loads General context so the composer's
  `start_conversation` works) + sets `greeting` + `section = "chat"`.
- `greeting: str` field, set in `load_home` via pure helper
  `_time_greeting(hour) -> "Good morning|afternoon|evening"`.
- Chip handlers:
  - `chip_query_bigquery()` — prefill `chat_input` with a BigQuery starter + focus.
  - `chip_new_project()` — redirect `/projects` and open the new-project dialog.
  - Browse chats → `/chats`; Customize → `/customize` (plain links).

### Sidebar / links — `sidebar.py`, `state.py`, `workspace_panels.py`
- Sidebar: `Projects` → `/projects`; `New chat` → `/`; `Chat` tab stays `/`.
- `workspace()` "All projects" back-link `/` → `/projects`.
- `new_chat()` → redirect `/`; post-delete `redirect("/")` (dashboard) → `/projects`.

## Testing
- Unit (TDD): `_time_greeting()` over the hour ranges (morning/afternoon/evening).
- Existing frontend tests stay green.
- Manual: `/` shows greeting + composer + chips; submit starts a streaming General
  chat; `/projects` shows the grid; sidebar links resolve correctly.

## YAGNI
No new chat backend, no sidebar redesign, no auth changes — landing + routing only.
