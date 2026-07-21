// A condensed list of the harness file-tool calls made this message (from tool_call
// events), distinct from the general per-call ToolCard already rendered for every tool.
export function ToolTimeline({ calls }: { calls: { id: string; name: string; ok: boolean }[] }) {
  return (
    <ol className="tool-timeline">
      {calls.map((c) => (
        <li key={c.id} data-ok={c.ok}>
          <code>{c.name}</code> <span aria-hidden="true">{c.ok ? "✓" : "✗"}</span>
        </li>
      ))}
    </ol>
  );
}
