import { useRef, useState } from "react";

import { Icon } from "../Icon";
import { DirCard, DirEmpty, DirToolbar } from "./DirCard";
import { RepoSyncModal } from "./RepoSyncModal";
import type { SkillControls } from "./types";

// Skills directory: browse installed skills, import a .md / .zip, or sync a repository.
export function SkillsPage({ c }: { c: SkillControls }) {
  const [q, setQ] = useState("");
  const [showRepo, setShowRepo] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const rows = c.list.filter((s) =>
    (s.name + " " + (s.description ?? "")).toLowerCase().includes(q.trim().toLowerCase()),
  );

  async function onFile(file: File | undefined) {
    if (!file) return;
    setErr(null);
    // A .zip is a skill FOLDER (SKILL.md + references/) — the server extracts it and
    // imports like a synced repo. Reading it as text would just store zip bytes.
    const failure = file.name.toLowerCase().endsWith(".zip")
      ? await c.importZip(file)
      : await c.importFile(file.name, await file.text());
    if (failure) setErr(failure);
  }

  return (
    <>
      {err && <div className="settings-err">{err}</div>}
      <p className="settings-hint">
        Skills are markdown instruction packs. Type <code>/</code> in the composer to invoke one;
        auto skills trigger on matching messages. Import a <code>.md</code> file or a{" "}
        <code>.zip</code> of a skill folder, or sync a whole repository of skills.
      </p>
      <div className="settings-toolbar">
        <DirToolbar q={q} onQ={setQ} placeholder="Search skills…" />
        <span className="settings-toolbar-spacer" />
        <label className="settings-add-file" title="A .md file, or a .zip of a skill folder (SKILL.md + references)">
          Import skill (.md / .zip)
          <input
            ref={fileRef}
            type="file"
            accept=".md,.markdown,.zip,text/markdown,text/plain,application/zip,application/x-zip-compressed"
            style={{ display: "none" }}
            onChange={(e) => {
              void onFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </label>
        <button className="settings-add" onClick={() => setShowRepo(true)}>
          <Icon name="plus" size={13} /> Add from repository
        </button>
      </div>
      <div className="dir-grid">
        {rows.map((s) => (
          <DirCard
            key={s.name}
            icon="bulb"
            title={`/${s.name}`}
            badges={
              <>
                {s.auto && <span className="badge-pill">auto</span>}
                {s.imported && <span className="badge-pill dir-origin">imported</span>}
              </>
            }
          >
            <p className="dir-card-desc">{s.description || "No description."}</p>
            <div className="dir-card-actions">
              {s.auto && (s.triggers ?? []).length > 0 ? (
                <span className="dir-card-foot">Triggers: {(s.triggers ?? []).join(", ")}</span>
              ) : (
                <span />
              )}
              {s.imported && (
                <button
                  className="dir-remove"
                  title="Remove imported skill"
                  aria-label={`Remove ${s.name}`}
                  onClick={() => c.onRemove(s.name)}
                >
                  <Icon name="x" size={14} />
                </button>
              )}
            </div>
          </DirCard>
        ))}
      </div>
      {rows.length === 0 && (
        <DirEmpty>{c.list.length === 0 ? "No skills yet — import one." : "No matches."}</DirEmpty>
      )}
      {showRepo && (
        <RepoSyncModal
          title="Add skills from a repository"
          blurb="Copy the markdown skill files from a GitHub repository or git URL into your skills."
          allowRemote={c.allowRemote}
          onSync={(url, ref) => c.importFromRepo(url, ref)}
          onClose={() => setShowRepo(false)}
        />
      )}
    </>
  );
}
