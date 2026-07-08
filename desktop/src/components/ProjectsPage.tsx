import { useEffect, useMemo, useRef, useState } from "react";

import type { Project } from "../api/client";
import { filterSortProjects, type ProjectSort, SORT_LABELS } from "../state/projectsView";
import { Icon } from "./Icon";

// The Projects grid (Claude Desktop parity): a search box, a Sort-by control, a
// "New project" button, and a grid of project cards. Each card shows the name,
// description, and a relative "Updated" time, with a ⋮ overflow menu
// (Pin/Unpin, Edit details, Archive, Delete). Pinned projects lead the grid.
export function ProjectsPage({
  list,
  onOpen,
  onNew,
  onEditDetails,
  onTogglePin,
  onArchive,
  onDelete,
}: {
  list: Project[];
  onOpen: (pid: string) => void;
  onNew: () => void;
  onEditDetails: (pid: string) => void;
  onTogglePin: (pid: string, pinned: boolean) => void;
  onArchive: (pid: string) => void;
  onDelete: (pid: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<ProjectSort>("updated");
  const [sortOpen, setSortOpen] = useState(false);
  const sortRef = useRef<HTMLDivElement>(null);

  const shown = useMemo(() => filterSortProjects(list, query, sort), [list, query, sort]);

  useEffect(() => {
    if (!sortOpen) return;
    function onDoc(e: MouseEvent) {
      if (!sortRef.current?.contains(e.target as Node)) setSortOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setSortOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [sortOpen]);

  return (
    <div className="projects-page">
      <header className="projects-head">
        <h1 className="projects-title">Projects</h1>
        <div className="projects-head-actions">
          <div className="proj-sort" ref={sortRef}>
            <button className="proj-sort-btn" aria-haspopup="menu" aria-expanded={sortOpen}
                    onClick={() => setSortOpen((o) => !o)}>
              Sort by <strong>{SORT_LABELS[sort]}</strong>
              <Icon name="chev-down" size={12} />
            </button>
            {sortOpen && (
              <div className="proj-sort-menu" role="menu">
                {(Object.keys(SORT_LABELS) as ProjectSort[]).map((s) => (
                  <button key={s} role="menuitemradio" aria-checked={sort === s}
                          className={sort === s ? "active" : ""}
                          onClick={() => { setSort(s); setSortOpen(false); }}>
                    {SORT_LABELS[s]}
                    {sort === s && <Icon name="check" size={14} />}
                  </button>
                ))}
              </div>
            )}
          </div>
          <button className="btn-primary" onClick={onNew}>New project</button>
        </div>
      </header>

      <div className="projects-search">
        <Icon name="search" size={16} />
        <input
          placeholder="Search projects…"
          aria-label="Search projects"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {shown.length === 0 ? (
        <div className="projects-empty">
          {query ? "No projects match your search." : "No projects yet. Create one to get started."}
        </div>
      ) : (
        <div className="projects-grid">
          {shown.map((p) => (
            <ProjectCard
              key={p.id}
              project={p}
              onOpen={() => onOpen(p.id)}
              onEditDetails={() => onEditDetails(p.id)}
              onTogglePin={() => onTogglePin(p.id, !p.pinned)}
              onArchive={() => onArchive(p.id)}
              onDelete={() => onDelete(p.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function ProjectCard({
  project,
  onOpen,
  onEditDetails,
  onTogglePin,
  onArchive,
  onDelete,
}: {
  project: Project;
  onOpen: () => void;
  onEditDetails: () => void;
  onTogglePin: () => void;
  onArchive: () => void;
  onDelete: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function onDoc(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  return (
    <div className="project-card" role="button" tabIndex={0}
         onClick={onOpen}
         onKeyDown={(e) => {
           // Only Enter/Space ON THE CARD itself opens it — keydowns bubbling up from the
           // ⋮ menu button or its items must not also navigate into the project.
           if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
             e.preventDefault();
             onOpen();
           }
         }}>
      <div className="project-card-top">
        <span className="project-card-name">
          {project.pinned && (
            <span className="project-card-pin" aria-label="Pinned"><Icon name="pin-filled" size={13} /></span>
          )}
          {project.name}
        </span>
        <div className="project-card-menu" ref={menuRef}>
          <button
            className="project-card-menu-btn"
            aria-label="Project options"
            aria-expanded={menuOpen}
            onClick={(e) => { e.stopPropagation(); setMenuOpen((o) => !o); }}
          >
            <Icon name="dots" size={16} />
          </button>
          {menuOpen && (
            <div className="card-menu" role="menu" onClick={(e) => e.stopPropagation()}>
              <button role="menuitem" onClick={() => { setMenuOpen(false); onTogglePin(); }}>
                <Icon name={project.pinned ? "pin" : "pin-filled"} size={14} />
                {project.pinned ? "Unpin" : "Pin"}
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); onEditDetails(); }}>
                <Icon name="pencil" size={14} /> Edit details
              </button>
              <button role="menuitem" onClick={() => { setMenuOpen(false); onArchive(); }}>
                <Icon name="archive" size={14} /> Archive
              </button>
              <button role="menuitem" className="danger" onClick={() => { setMenuOpen(false); onDelete(); }}>
                <Icon name="trash" size={14} /> Delete
              </button>
            </div>
          )}
        </div>
      </div>
      <p className="project-card-desc">
        {project.description?.trim() || "No description yet."}
      </p>
      <div className="project-card-foot">Updated {project.updated_rel || "recently"}</div>
    </div>
  );
}
