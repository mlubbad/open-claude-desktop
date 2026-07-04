import { useEffect, useRef } from "react";

import { isEditableTarget } from "./shortcuts";

// App-wide keyboard shortcuts. Handlers are kept in a ref so the listener is
// registered once and always calls the latest closures.
export interface KeyHandlers {
  onEscape?: () => void;
  onNewChat?: () => void;
  onPalette?: () => void;
  onHelp?: () => void;
}

export function useKeyboard(handlers: KeyHandlers): void {
  const ref = useRef(handlers);
  ref.current = handlers;

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        ref.current.onEscape?.();
        return;
      }
      // Cmd/Ctrl+K -> command palette
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ref.current.onPalette?.();
        return;
      }
      // Cmd/Ctrl+Shift+O -> new chat
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "o") {
        e.preventDefault();
        ref.current.onNewChat?.();
        return;
      }
      // "?" -> shortcuts help, but never while typing (it's a printable character).
      if (e.key === "?" && !e.metaKey && !e.ctrlKey && !isEditableTarget(e.target)) {
        e.preventDefault();
        ref.current.onHelp?.();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
