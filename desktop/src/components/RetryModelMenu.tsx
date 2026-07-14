import { useEffect, useRef, useState } from "react";

import { type ProviderInfo, providers as providerApi, settings as settingsApi } from "../api/client";
import { effectiveCatalog, modelDescriptor, pickerModels } from "../state/modelMeta";
import { Icon } from "./Icon";

// Compact popover on the last reply's retry control: pick any usable model — across all
// BYOK providers — to regenerate the answer with. Only providers that are ready to use
// (local, or with a key on file) are offered, so a pick never fails for a missing key.
// Each provider's rows are narrowed to the user's Settings selection (or the newest few),
// mirroring the composer's model picker.
export function RetryModelMenu({
  current,
  onPick,
  onClose,
}: {
  current: { provider: string; model: string };
  onPick: (provider: string, model: string) => void;
  onClose: () => void;
}) {
  const [list, setList] = useState<ProviderInfo[]>([]);
  const [visible, setVisible] = useState<Record<string, string[]>>({});
  const [custom, setCustom] = useState<Record<string, string[]>>({});
  const [hidden, setHidden] = useState<Record<string, string[]>>({});
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    providerApi.list().then(setList).catch(() => {});
    settingsApi
      .get()
      .then((s) => {
        setVisible(s.visible_models ?? {});
        setCustom(s.custom_models ?? {});
        setHidden(s.hidden_models ?? {});
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (!ref.current?.contains(e.target as Node)) onClose();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        e.preventDefault();
        onClose();
      }
    }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [onClose]);

  // Ready-to-use providers only: local ones, ones with a key on file, or ones that
  // need no key at all. Offering a keyless remote provider would just error on submit.
  const usable = list.filter((p) => p.is_local || p.has_key || !p.requires_key);

  return (
    <div className="retry-menu" ref={ref} role="menu" aria-label="Regenerate with a different model">
      <div className="retry-menu-head">Regenerate with…</div>
      <div className="retry-menu-scroll">
        {list.length > 0 && usable.length === 0 && (
          <div className="retry-menu-empty">No ready-to-use models — add a key in Settings.</div>
        )}
        {usable.map((p) => {
          const catalog = effectiveCatalog(p.models ?? [], custom[p.id], hidden[p.id]);
          const models = pickerModels(catalog, visible[p.id], p.id === current.provider ? current.model : "");
          if (!models.length) return null;
          return (
            <div key={p.id} className="retry-menu-group">
              <div className="retry-menu-provider">{p.label}</div>
              {models.map((m) => {
                const active = p.id === current.provider && m === current.model;
                return (
                  <button
                    key={m}
                    role="menuitem"
                    className={`retry-menu-item ${active ? "active" : ""}`}
                    onClick={() => onPick(p.id, m)}
                  >
                    <span className="retry-menu-meta">
                      <span className="retry-menu-name">{m.split("/").pop()}</span>
                      <span className="retry-menu-desc">{modelDescriptor(m)}</span>
                    </span>
                    {active && (
                      <span className="retry-menu-cur" aria-hidden="true">
                        <Icon name="check" size={13} />
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
