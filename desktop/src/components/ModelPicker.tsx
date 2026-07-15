import { useEffect, useRef, useState } from "react";

import { type ProviderInfo, providers as providerApi, settings as settingsApi } from "../api/client";
import { effectiveCatalog, EFFORT_LEVELS, modelDescriptor, pickerModels } from "../state/modelMeta";
import { useMenuFit } from "../state/useMenuFit";
import { Icon } from "./Icon";

// The two-column Model + Effort popover opened from the composer's model control
// (contract §3). Left column = effort levels + Thinking toggle; right column = the
// active provider's models with descriptors + checkmark, then Effort value and a
// "More models" jump into Settings. Selections apply instantly via the callbacks;
// the caller persists them per conversation.
export function ModelPicker({
  provider,
  model,
  effort,
  thinking,
  onSelectModel,
  onSelectEffort,
  onToggleThinking,
  onMoreModels,
  onClose,
}: {
  provider: string;
  model: string;
  effort: string;
  thinking: boolean;
  onSelectModel: (provider: string, model: string) => void;
  onSelectEffort: (effort: string) => void;
  onToggleThinking: (on: boolean) => void;
  onMoreModels: () => void;
  onClose: () => void;
}) {
  const [list, setList] = useState<ProviderInfo[]>([]);
  const [visible, setVisible] = useState<Record<string, string[]>>({});
  const [custom, setCustom] = useState<Record<string, string[]>>({});
  const [hidden, setHidden] = useState<Record<string, string[]>>({});
  const ref = useRef<HTMLDivElement>(null);
  useMenuFit(ref, true); // the popover is only mounted while open

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

  // Models for the active provider (fall back to just the current model if the
  // provider list hasn't loaded yet), narrowed to the user's picker selection —
  // or the newest few by default. The rest live behind "More models & keys".
  const active = list.find((p) => p.id === provider);
  const catalog = active ? effectiveCatalog(active.models, custom[provider], hidden[provider]) : [];
  const models = catalog.length ? pickerModels(catalog, visible[provider], model) : [model];

  return (
    <div className="mp-pop" ref={ref} role="dialog" aria-label="Model and effort">
      {/* Left column — effort */}
      <div className="mp-col mp-effort">
        <p className="mp-help">
          Higher effort means more thorough responses, but takes longer and uses your limits faster.
        </p>
        {EFFORT_LEVELS.map((lvl) => (
          <button
            key={lvl.value}
            className={`mp-row ${effort === lvl.value ? "sel" : ""}`}
            onClick={() => onSelectEffort(lvl.value)}
          >
            <span className="mp-row-label">
              {lvl.value}
              {lvl.tag && <span className="mp-tag">{lvl.tag}</span>}
              {lvl.info && <span className="mp-info" aria-hidden="true">ⓘ</span>}
            </span>
            {effort === lvl.value && <span className="mp-check" aria-hidden="true"><Icon name="check" size={14} /></span>}
          </button>
        ))}
        <div className="mp-divider" />
        <div className="mp-thinking">
          <span className="mp-thinking-meta">
            <span className="mp-row-label">Thinking</span>
            <span className="mp-thinking-help">Can think for more complex tasks</span>
          </span>
          <button
            className={`mp-switch ${thinking ? "on" : ""}`}
            role="switch"
            aria-checked={thinking}
            aria-label="Thinking"
            onClick={() => onToggleThinking(!thinking)}
          >
            <span className="mp-switch-knob" />
          </button>
        </div>
      </div>

      {/* Right column — models */}
      <div className="mp-col mp-models">
        {models.map((m) => (
          <button
            key={m}
            className={`mp-row mp-model ${m === model ? "sel" : ""}`}
            onClick={() => onSelectModel(provider, m)}
          >
            <span className="mp-model-meta">
              <span className="mp-model-name">{m.split("/").pop()}</span>
              <span className="mp-model-desc">{modelDescriptor(m)}</span>
            </span>
            {m === model && <span className="mp-check" aria-hidden="true"><Icon name="check" size={14} /></span>}
          </button>
        ))}
        <div className="mp-divider" />
        <div className="mp-row mp-static">
          <span className="mp-row-label">Effort</span>
          <span className="mp-row-value">{effort}</span>
        </div>
        <button className="mp-row mp-more" onClick={onMoreModels}>
          <span className="mp-row-label">More models &amp; keys</span>
          <span className="mp-chev" aria-hidden="true"><Icon name="chev-right" size={13} /></span>
        </button>
      </div>
    </div>
  );
}
