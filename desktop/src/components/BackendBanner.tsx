import { useBackendHealth } from "../state/useBackendHealth";

// A thin banner shown when the backend sidecar can't be reached. The Tauri shell
// auto-restarts a dead sidecar, so this is usually a brief blip while it comes back; the
// copy stays honest for the case where the restart budget is spent and the user needs to
// relaunch. Fixed to the top so it never disturbs the app's flex layout.
export function BackendBanner() {
  const healthy = useBackendHealth();
  if (healthy) return null;
  return (
    <div className="backend-banner" role="alert">
      Can’t reach the local backend — reconnecting… If this keeps happening, restart the app.
    </div>
  );
}
