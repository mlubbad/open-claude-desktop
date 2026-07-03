import { type KeyboardEvent, useState } from "react";

export function Composer({
  busy,
  onSend,
  onStop,
}: {
  busy: boolean;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [text, setText] = useState("");

  function submit() {
    if (!text.trim() || busy) return;
    onSend(text);
    setText("");
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <div className="composer">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKey}
        placeholder="Message Open Claude Desktop…"
        rows={1}
      />
      {busy ? (
        <button className="stop" onClick={onStop} title="Stop">
          ■
        </button>
      ) : (
        <button className="send" onClick={submit} disabled={!text.trim()} title="Send">
          ↑
        </button>
      )}
    </div>
  );
}
