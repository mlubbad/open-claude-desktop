import { useEffect, useRef, useState } from "react";

import { composeAnswers, type QuestionBlock } from "../state/transcript";
import { Icon } from "./Icon";

// The inline structured-question card (contract §5.1): one question at a time with a
// pager, numbered options, a "Something else" freeform row + Skip, and an
// "Or reply directly…" escape hatch. Keyboard-navigable (↑↓ to move, Enter to pick).
// Answering composes a "Q:/A:" summary and posts it as the next turn.
export function QuestionCard({
  block,
  busy,
  onSubmit,
}: {
  block: QuestionBlock;
  busy: boolean;
  onSubmit: (id: string, text: string) => void;
}) {
  const [page, setPage] = useState(0);
  // Per-question chosen answer text (option label or freeform).
  const [answers, setAnswers] = useState<string[]>(() => block.questions.map(() => ""));
  const [active, setActive] = useState(0); // highlighted option index
  const [other, setOther] = useState("");
  const [reply, setReply] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);

  const q = block.questions[page];
  const total = block.questions.length;
  const isLast = page >= total - 1;

  // Focus the card so its keydown handler receives ↑↓/Enter immediately.
  useEffect(() => {
    if (!block.answered) rootRef.current?.focus();
  }, [block.answered]);

  if (block.answered) {
    return (
      <div className="qcard answered">
        <span className="qcard-done"><Icon name="check" size={13} /> Answered</span>
      </div>
    );
  }

  function record(pageIdx: number, value: string) {
    setAnswers((prev) => {
      const next = prev.slice();
      next[pageIdx] = value;
      return next;
    });
  }

  function finish(finalAnswers: string[]) {
    const text = composeAnswers(
      block.questions.map((qq, i) => ({ question: qq.title, answer: finalAnswers[i] ?? "" })),
    );
    // Even an all-skip still advances the turn (empty → a gentle "skip" note).
    onSubmit(block.id, text || "(skipped the questions — please continue)");
  }

  function choose(value: string) {
    const next = answers.slice();
    next[page] = value;
    setAnswers(next);
    if (isLast) {
      finish(next);
    } else {
      setPage((p) => p + 1);
      setActive(0);
      setOther("");
    }
  }

  function onKey(e: React.KeyboardEvent) {
    // The freeform inputs handle their own keys.
    if ((e.target as HTMLElement).tagName === "INPUT") return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, q.options.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(q.options[active]);
    }
  }

  return (
    <div className="qcard" ref={rootRef} tabIndex={-1} role="group" aria-label={q.title} onKeyDown={onKey}>
      <div className="qcard-head">
        <span className="qcard-title">{q.title}</span>
        {total > 1 && (
          <span className="qcard-pager">
            <button className="qcard-page-btn" aria-label="Previous question" disabled={page === 0}
                    onClick={() => { setPage((p) => Math.max(0, p - 1)); setActive(0); }}>
              <Icon name="chev-right" size={13} className="flip" />
            </button>
            {page + 1} of {total}
            <button className="qcard-page-btn" aria-label="Next question" disabled={isLast}
                    onClick={() => { setPage((p) => Math.min(total - 1, p + 1)); setActive(0); }}>
              <Icon name="chev-right" size={13} />
            </button>
          </span>
        )}
      </div>

      <div className="qcard-options">
        {q.options.map((opt, i) => (
          <button
            key={i}
            className={`qcard-opt ${i === active ? "active" : ""}`}
            onMouseEnter={() => setActive(i)}
            onClick={() => choose(opt)}
          >
            <span className="qcard-num">{i + 1}</span>
            <span className="qcard-opt-label">{opt}</span>
            <span className="qcard-arrow" aria-hidden="true"><Icon name="arrow-right" size={14} /></span>
          </button>
        ))}
      </div>

      {q.allowOther && (
        <div className="qcard-other">
          <span className="qcard-other-ic" aria-hidden="true"><Icon name="pencil" size={13} /></span>
          <input
            className="qcard-other-input"
            placeholder="Something else"
            aria-label="Something else"
            value={other}
            onChange={(e) => setOther(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && other.trim()) choose(other.trim()); }}
          />
          <button className="qcard-skip" onClick={() => choose("")}>
            {isLast ? "Skip" : "Skip"}
          </button>
        </div>
      )}

      <div className="qcard-reply">
        <input
          className="qcard-reply-input"
          placeholder="Or reply directly…"
          aria-label="Or reply directly"
          value={reply}
          disabled={busy}
          onChange={(e) => setReply(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && reply.trim()) {
              record(page, reply.trim());
              onSubmit(block.id, reply.trim());
            }
          }}
        />
      </div>

      <div className="qcard-hint">↑↓ to navigate · Enter to select · or type below</div>
    </div>
  );
}
