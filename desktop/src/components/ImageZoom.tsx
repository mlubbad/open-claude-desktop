import { useEffect, useState } from "react";

// A clickable image thumbnail that opens a full-size lightbox overlay — click the
// backdrop, the ✕, or press Escape to close — mirroring Claude Desktop's attachment
// preview. Drop-in replacement for a plain <img> in the composer and the transcript.
export function ImageZoom({
  src,
  alt,
  className,
}: {
  src: string;
  alt: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <img
        src={src}
        alt={alt}
        className={className}
        role="button"
        tabIndex={0}
        title="Click to enlarge"
        style={{ cursor: "zoom-in" }}
        onClick={(e) => {
          e.stopPropagation();
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen(true);
          }
        }}
      />
      {open && (
        <div
          className="lightbox-overlay"
          role="dialog"
          aria-modal="true"
          aria-label={alt}
          onClick={() => setOpen(false)}
        >
          <button
            type="button"
            className="lightbox-close"
            aria-label="Close image preview"
            onClick={() => setOpen(false)}
          >
            ✕
          </button>
          <img
            src={src}
            alt={alt}
            className="lightbox-img"
            onClick={(e) => e.stopPropagation()}
          />
        </div>
      )}
    </>
  );
}
