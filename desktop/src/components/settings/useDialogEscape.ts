import { useEffect, useRef } from "react";

// Escape closes just this dialog. A capture-phase window listener runs before the
// app-wide Escape handler (which would otherwise close the whole Settings modal) and
// stops it, regardless of where focus currently sits.
export function useDialogEscape(onClose: () => void): void {
  const ref = useRef(onClose);
  ref.current = onClose;
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        e.preventDefault();
        ref.current();
      }
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);
}
