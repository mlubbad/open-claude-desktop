// A unified diff from an edit_file call (harness file_diff event), rendered line-by-line
// with add/del/context styling. write_file has no "before" to diff against, so it never
// produces one of these.
export function FileDiffCard({ diff }: { diff: string }) {
  return (
    <pre className="file-diff">
      {diff.split("\n").map((line, i) => {
        const cls =
          line.startsWith("+") && !line.startsWith("+++")
            ? "add"
            : line.startsWith("-") && !line.startsWith("---")
              ? "del"
              : "ctx";
        return (
          <div key={i} className={`diff-line ${cls}`}>
            {line}
          </div>
        );
      })}
    </pre>
  );
}
