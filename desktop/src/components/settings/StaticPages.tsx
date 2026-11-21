// The Settings pages that mirror Claude Desktop's layout but whose backends do not
// exist in this build: every control renders faithfully and DISABLED (tooltip:
// "Not available in this build yet"). One file — each page is a thin composition of
// the shared controls; splitting them into files apiece would just be ceremony.

import type { ReactNode } from "react";

import { InlineSelect, LockedButton, Row, Section, Segmented, Toggle } from "./controls";

// A one-line banner explaining why a page is inert, with an optional pointer.
function PageNote({ children }: { children: ReactNode }) {
  return <p className="settings-hint set-page-note">{children}</p>;
}

export function AccountPage() {
  return (
    <>
      <PageNote>
        This build is local-first with your own API keys — there is no hosted account.
        Model access is configured under <b>Models &amp; keys</b>.
      </PageNote>
      <Section title="Account">
        <Row label="Log out of all devices" locked>
          <LockedButton>Log out</LockedButton>
        </Row>
        <Row label="Delete account" desc="To delete your account, cancel your subscription first." locked>
          <LockedButton>Delete account</LockedButton>
        </Row>
        <Row label="Organization ID" locked>
          <span className="set-muted">—</span>
        </Row>
      </Section>
      <Section title="Trusted devices">
        <Row label="Devices that can approve sign-ins from other devices" locked>
          <span className="set-muted">No trusted devices</span>
        </Row>
      </Section>
      <Section title="Active sessions">
        <Row label="Signed-in devices" locked>
          <span className="set-muted">This device</span>
        </Row>
      </Section>
    </>
  );
}

export function PrivacyPage() {
  return (
    <>
      <PageNote>
        Everything stays on this machine: conversations, files, and settings are stored
        locally, and prompts go only to the model providers you configure.
      </PageNote>
      <Section title="Preferences">
        <Row label="Location metadata"
             desc="Allow Claude to use coarse location metadata (city/region) to improve product experiences." locked>
          <Toggle label="Location metadata" on={false} disabled />
        </Row>
        <Row label="Help improve our AI models"
             desc="Nothing is collected in this build — no telemetry, no training on your chats." locked>
          <Toggle label="Help improve our AI models" on={false} disabled />
        </Row>
      </Section>
      <Section title="Your data">
        <Row label="Export data"
             desc="Individual conversations can be exported from the chat's share menu (Markdown or JSON)." locked>
          <LockedButton>Export data</LockedButton>
        </Row>
        <Row label="Shared chats" locked>
          <LockedButton>Manage</LockedButton>
        </Row>
        <Row label="Shared artifacts" locked>
          <LockedButton>Manage</LockedButton>
        </Row>
        <Row label="Memory preferences" locked>
          <LockedButton>Manage</LockedButton>
        </Row>
      </Section>
    </>
  );
}

export function BillingPage() {
  return (
    <>
      <PageNote>
        There is no subscription: you bring your own API keys, and usage is billed by
        your providers directly. Manage keys under <b>Models &amp; keys</b>.
      </PageNote>
      <Section title="Plan">
        <Row label="Current plan" locked>
          <span className="set-muted">BYOK — no plan</span>
        </Row>
        <Row label="Payment" locked>
          <LockedButton>Update</LockedButton>
        </Row>
      </Section>
      <Section title="Invoices">
        <Row label="Billing history" locked>
          <span className="set-muted">See your provider's dashboard</span>
        </Row>
      </Section>
    </>
  );
}

export function UsagePage() {
  return (
    <>
      <PageNote>
        Usage limits are enforced by your model providers, not by this app — check each
        provider's dashboard for quotas and spend. A per-turn cost estimate is shown at
        the end of every response.
      </PageNote>
      <Section title="Plan usage limits">
        <Row label="Current session" locked>
          <div className="set-meter" aria-hidden><span style={{ width: "0%" }} /></div>
        </Row>
        <Row label="Weekly limits" desc="All models" locked>
          <div className="set-meter" aria-hidden><span style={{ width: "0%" }} /></div>
        </Row>
      </Section>
      <Section title="Usage credits">
        <Row label="Turn on usage credits to keep using Claude if you hit a limit" locked>
          <Toggle label="Usage credits" on={false} disabled />
        </Row>
        <Row label="Buy usage credits" locked>
          <LockedButton>Buy usage credits</LockedButton>
        </Row>
      </Section>
    </>
  );
}

export function ClaudeCodePage() {
  return (
    <>
      <PageNote>
        The Code surface in this build is a basic workspace; these session, browser, and
        pull-request controls arrive as it grows.
      </PageNote>
      <Section title="General">
        <Row label="Classify session states"
             desc="Allow Claude to automatically classify sessions as blocked, ready for review, or done." locked>
          <Toggle label="Classify session states" on={false} disabled />
        </Row>
        <Row label="Switch models when a message is flagged"
             desc="When safety measures flag a message, automatically switch to a different model to keep chatting." locked>
          <Toggle label="Switch models when a message is flagged" on={false} disabled />
        </Row>
      </Section>
      <Section title="Code appearance">
        <Row label="Light / dark code themes" locked>
          <InlineSelect label="Code themes" value="claude" disabled
                        options={[{ value: "claude", label: "Claude Light · Claude Dark" }]} />
        </Row>
        <Row label="Code font" desc="Set a custom monospace font for code and terminal." locked>
          <input className="set-input" placeholder="e.g. JetBrains Mono" disabled aria-label="Code font" />
        </Row>
      </Section>
      <Section title="Appearance">
        <Row label="High-contrast dark theme" desc="Use a darker, near-black background when dark mode is on." locked>
          <Toggle label="High-contrast dark theme" on={false} disabled />
        </Row>
        <Row label="Interface font" locked>
          <Segmented label="Interface font" value="serif" disabled
                     options={[{ value: "serif", label: "Serif" }, { value: "system", label: "System" }]} />
        </Row>
        <Row label="Transcript text size" locked>
          <Segmented label="Transcript text size" value="medium" disabled
                     options={[{ value: "small", label: "Small" }, { value: "medium", label: "Medium" }, { value: "large", label: "Large" }]} />
        </Row>
        <Row label="Transcript width" locked>
          <Segmented label="Transcript width" value="narrow" disabled
                     options={[{ value: "narrow", label: "Narrow" }, { value: "medium", label: "Medium" }, { value: "wide", label: "Wide" }]} />
        </Row>
      </Section>
      <Section title="Local sessions">
        <Row label="Allow bypass permissions mode"
             desc="Bypass all permission checks and let Claude work uninterrupted. Risky — can result in data loss." locked>
          <Toggle label="Allow bypass permissions mode" on={false} disabled />
        </Row>
        <Row label="Dynamic workflows"
             desc="Let Claude run multiple agents in parallel for complex tasks." locked>
          <Toggle label="Dynamic workflows" on={false} disabled />
        </Row>
        <Row label="Worktree location" desc="Where to store git worktrees for isolated coding sessions." locked>
          <InlineSelect label="Worktree location" value="in" disabled
                        options={[{ value: "in", label: "Inside project (.claude/…)" }]} />
        </Row>
      </Section>
      <Section title="Pull requests">
        <Row label="Branch prefix" desc="Prefix added to branch names." locked>
          <input className="set-input" defaultValue="claude" disabled aria-label="Branch prefix" />
        </Row>
        <Row label="Create pull requests automatically" locked>
          <Toggle label="Create pull requests automatically" on={false} disabled />
        </Row>
        <Row label="Autofix pull requests"
             desc="Automatically monitor new pull requests for CI failures and review comments." locked>
          <Toggle label="Autofix pull requests" on={false} disabled />
        </Row>
      </Section>
      <Section title="Authorization tokens">
        <Row label="Tokens created when you sign in to Claude Code" locked>
          <span className="set-muted">None</span>
        </Row>
      </Section>
    </>
  );
}

export function CoworkPage() {
  return (
    <>
      <PageNote>
        Cowork runs background tasks from the Cowork tab. Folder trust and phone
        dispatch aren't implemented yet.
      </PageNote>
      <Section title="Cowork">
        <Row label="Dispatch" badge="Beta"
             desc="Let Claude work on tasks from your phone using this computer." locked>
          <Toggle label="Dispatch" on={false} disabled />
        </Row>
        <Row label="Cowork files" desc="Where artifacts and scheduled tasks are stored." locked>
          <LockedButton>Change</LockedButton>
        </Row>
        <Row label="Trusted Cowork folders"
             desc="When you attach one of these folders to a Cowork task, Claude won't ask you to confirm." locked>
          <LockedButton>Manage</LockedButton>
        </Row>
        <Row label="Global instructions"
             desc="Instructions that apply to all Cowork sessions live in General → Instructions for Claude." locked>
          <LockedButton>Edit</LockedButton>
        </Row>
      </Section>
    </>
  );
}

export function ChromePage() {
  return (
    <>
      <PageNote>There is no browser extension for this build yet.</PageNote>
      <Section title="Claude in Chrome">
        <Row label="Site permissions" desc="Choose whether Claude in Chrome works on a site by default." locked>
          <InlineSelect label="Site permissions" value="ask" disabled
                        options={[{ value: "ask", label: "Default is to ask" }]} />
        </Row>
        <Row label="Allowed sites" locked>
          <LockedButton>Add website</LockedButton>
        </Row>
        <Row label="Blocked sites" desc="Claude in Chrome cannot browse these sites." locked>
          <span className="set-muted">No sites added yet</span>
        </Row>
      </Section>
    </>
  );
}

// DesktopGeneralPage moved to its own file — it grew a real backend (P1-9: live
// hotkey/tray/login/update controls), so it no longer belongs with the inert pages.
