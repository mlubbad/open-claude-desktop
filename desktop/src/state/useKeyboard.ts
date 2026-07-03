import { useEffect, useRef } from "react";

// App-wide keyboard shortcuts. Handlers are kept in a ref so the listener is
// registered once and always calls the latest closures.
export interface KeyHandlers {
  onEscape?: () => void;
  onNewChat?: () => void;
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
      // Cmd/Ctrl+Shift+O -> new chat
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key.toLowerCase() === "o") {
        e.preventDefault();
        ref.current.onNewChat?.();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}
