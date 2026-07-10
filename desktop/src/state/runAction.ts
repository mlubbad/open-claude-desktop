// Shared wrapper for the "busy + clear-error + run + refresh" async-action pattern that
// the data hooks (useSkills/usePlugins/…) repeated almost verbatim. Runs `fn`; on success
// refreshes and returns null; on failure returns the error message (never throws). The
// caller decides how to surface the returned message. Any of the hooks is optional so the
// same helper fits actions with or without a busy flag / refresh step.

export interface ActionHooks {
  setBusy?: (b: boolean) => void;
  setErr?: (e: string | null) => void;
  refresh?: () => Promise<void> | void;
}

export async function runAction(
  fn: () => Promise<unknown>,
  { setBusy, setErr, refresh }: ActionHooks = {},
): Promise<string | null> {
  setBusy?.(true);
  setErr?.(null);
  try {
    await fn();
    await refresh?.();
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  } finally {
    setBusy?.(false);
  }
}
