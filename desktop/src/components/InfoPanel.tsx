import type { ProjectFile } from "../api/client";
import type { ArtifactDoc } from "../state/transcript";
import { Icon } from "./Icon";

// The conversation info rail: everything this thread produced (artifacts) and the
// knowledge the project grounds it with. Opens from the panel toggle in the top bar.
export function InfoPanel({
  artifacts,
  projectName,
  files,
  onOpenArtifact,
  onManageProject,
  onClose,
}: {
  artifacts: ArtifactDoc[];
  projectName: string | null;
  files: ProjectFile[];
  onOpenArtifact: (id: string) => void;
  onManageProject: () => void;
  onClose: () => void;
}) {
  return (
    <aside className="info-panel" aria-label="Conversation info">
      <div className="info-head">
        <span className="info-title">Details</span>
        <button className="info-close" title="Close" aria-label="Close panel" onClick={onClose}>
          <Icon name="x" size={14} />
        </button>
      </div>
      <div className="info-body">
        <section className="info-sec">
          <h3 className="info-sec-title">Artifacts</h3>
          {artifacts.length === 0 && <div className="info-empty">Nothing created in this chat yet.</div>}
          {artifacts.map((a) => (
            <button key={a.id} className="info-row" onClick={() => onOpenArtifact(a.id)}>
              <span className="info-row-icon" aria-hidden="true">
                <Icon name="file" size={16} />
              </span>
              <span className="info-row-meta">
                <span className="info-row-title">{a.title}</span>
                <span className="info-row-sub">
                  {a.kind}
                  {a.version > 1 ? ` · v${a.version}` : ""}
                </span>
              </span>
              <span className="info-row-open" aria-hidden="true">
                <Icon name="chev-right" size={13} />
              </span>
            </button>
          ))}
        </section>

        {projectName && (
          <section className="info-sec">
            <h3 className="info-sec-title">Project content</h3>
            <div className="info-proj-card">
              <div className="info-proj-name">
                <span className="info-row-icon" aria-hidden="true">
                  <Icon name="folder" size={15} />
                </span>
                {projectName}
              </div>
              {files.length === 0 && <div className="info-empty">No knowledge files uploaded.</div>}
              <div className="info-files">
                {files.map((f) => (
                  <div key={f.name} className="info-file" title={f.name}>
                    <span className="info-file-name">{f.name}</span>
                    {f.meta && <span className="info-file-meta">{f.meta}</span>}
                    <span className="info-file-badge">{f.badge}</span>
                  </div>
                ))}
              </div>
              <button className="info-manage" onClick={onManageProject}>
                Manage project
              </button>
            </div>
          </section>
        )}
      </div>
    </aside>
  );
}
