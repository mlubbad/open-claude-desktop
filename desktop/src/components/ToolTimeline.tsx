// A condensed list of the harness file-tool calls made this message (from tool_call
// events), distinct from the general per-call ToolCard already rendered for every tool.
// Note: failed calls are intentionally absent here (harness tool_call always carries
// ok: true today; a failure shows via the generic tool_error/ToolCard instead) -- the
// ok/failed styling exists for forward-compatibility, not a currently-reachable case.
export function ToolTimeline({ calls }: { calls: { id: string; name: string; ok: boolean }[] }) {
  return (
    <ol className="tool-timeline">
      {calls.map((c) => (
        <li key={c.id} data-ok={c.ok}>
          <code>{c.name}</code>{" "}
          <span aria-hidden="true">{c.ok ? "✓" : "✗"}</span>
          <span className="sr-only">{c.ok ? "succeeded" : "failed"}</span>
        </li>
      ))}
    </ol>
  );
}
