// Small inline SVG line-icon set (16px, 1.5px stroke, currentColor) replacing the
// emoji glyphs across the chrome. Icon-only buttons must pass `label` (or put an
// aria-label on the button); decorative uses stay aria-hidden.

export type IconName =
  | "pencil"
  | "plus"
  | "x"
  | "pin"
  | "pin-filled"
  | "sun"
  | "moon"
  | "half"
  | "download"
  | "clock"
  | "folder"
  | "sliders"
  | "copy"
  | "retry"
  | "pen"
  | "book"
  | "bug"
  | "chart"
  | "note"
  | "bulb"
  | "check"
  | "arrow-down"
  | "thumb-up"
  | "thumb-down"
  | "file"
  | "panel"
  | "chev-down"
  | "chev-right"
  | "dots"
  | "archive"
  | "trash"
  | "image"
  | "mic"
  | "waveform"
  | "arrow-up"
  | "arrow-right"
  | "share"
  | "search"
  | "pin-angle"
  | "eye"
  | "eye-off"
  | "code"
  | "expand"
  | "cloud-up";

const PATHS: Record<IconName, React.ReactNode> = {
  pencil: <path d="M11.3 2.7l2 2L5 13H3v-2l8.3-8.3zM10 4l2 2" />,
  plus: <path d="M8 3.5v9M3.5 8h9" />,
  x: <path d="M4.5 4.5l7 7m0-7l-7 7" />,
  pin: <path d="M8 2.5l1.7 3.4 3.8.6-2.7 2.7.6 3.8L8 11.2 4.6 13l.6-3.8L2.5 6.5l3.8-.6L8 2.5z" />,
  "pin-filled": (
    <path d="M8 2.5l1.7 3.4 3.8.6-2.7 2.7.6 3.8L8 11.2 4.6 13l.6-3.8L2.5 6.5l3.8-.6L8 2.5z" fill="currentColor" />
  ),
  sun: (
    <>
      <circle cx="8" cy="8" r="3" />
      <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4" />
    </>
  ),
  moon: <path d="M13 9.5A5.5 5.5 0 0 1 6.5 3 5.5 5.5 0 1 0 13 9.5z" />,
  half: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 2.5a5.5 5.5 0 0 1 0 11z" fill="currentColor" stroke="none" />
    </>
  ),
  download: <path d="M8 2.5v7M4.8 6.8L8 10l3.2-3.2M3 13h10" />,
  clock: (
    <>
      <circle cx="8" cy="8" r="5.5" />
      <path d="M8 5v3.2l2.2 1.3" />
    </>
  ),
  folder: <path d="M2 4h4l1.5 1.5H14V12.5H2V4z" />,
  sliders: (
    <>
      <path d="M2.5 5h11M2.5 11h11" />
      <circle cx="6" cy="5" r="1.6" fill="var(--surface, #fff)" />
      <circle cx="10" cy="11" r="1.6" fill="var(--surface, #fff)" />
    </>
  ),
  copy: (
    <>
      <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" />
      <path d="M10.5 5.5v-2a1 1 0 0 0-1-1h-6a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2" />
    </>
  ),
  retry: <path d="M13 8a5 5 0 1 1-1.5-3.5M13 2.5v3h-3" />,
  pen: <path d="M2.5 13.5c.5-2 1.2-3.3 2.5-4.5L11.5 2.5l2 2L7 11c-1.2 1.3-2.5 2-4.5 2.5z" />,
  book: <path d="M8 3.5C6.5 2.5 4.5 2.5 2.5 3v9.5c2-.5 4-.5 5.5.5 1.5-1 3.5-1 5.5-.5V3c-2-.5-4-.5-5.5.5v9.5" />,
  bug: (
    <>
      <circle cx="8" cy="9" r="3.5" />
      <path d="M8 5.5V4M5.5 3.5L6.7 5M10.5 3.5L9.3 5M2.5 9h2M11.5 9h2M3.5 12.5l1.6-1.4M12.5 12.5l-1.6-1.4" />
    </>
  ),
  chart: <path d="M3 13V8M7 13V4M11 13V6M14 13H2" />,
  note: <path d="M4 2.5h8v11H4v-11zM6 5.5h4M6 8h4M6 10.5h2.5" />,
  bulb: <path d="M8 2.5a4 4 0 0 1 2.3 7.2c-.5.4-.8.9-.8 1.5v.3H6.5v-.3c0-.6-.3-1.1-.8-1.5A4 4 0 0 1 8 2.5zM6.5 13.5h3" />,
  check: <path d="M3.5 8.5l3 3 6-6.5" />,
  "arrow-down": <path d="M8 3v10M4.5 9.5L8 13l3.5-3.5" />,
  "thumb-up": (
    <>
      <path d="M2.5 7.5h2v6h-2z" />
      <path d="M4.5 13.5h6.6c.7 0 1.2-.4 1.4-1.1l.9-3.6c.2-.9-.5-1.6-1.3-1.6H8.9l.6-2.7c.2-.9-.5-1.7-1.4-1.7L5.3 7.3c-.5.6-.8 1.3-.8 2.1" />
    </>
  ),
  "thumb-down": (
    <>
      <path d="M2.5 8.5h2v-6h-2z" />
      <path d="M4.5 2.5h6.6c.7 0 1.2.4 1.4 1.1l.9 3.6c.2.9-.5 1.6-1.3 1.6H8.9l.6 2.7c.2.9-.5 1.7-1.4 1.7L5.3 8.7c-.5-.6-.8-1.3-.8-2.1" />
    </>
  ),
  file: <path d="M4 2h5l3 3v9H4V2zM9 2v3h3" />,
  panel: (
    <>
      <rect x="2" y="3" width="12" height="10" rx="1.5" />
      <path d="M10 3v10" />
    </>
  ),
  "chev-down": <path d="M4.5 6.5L8 10l3.5-3.5" />,
  "chev-right": <path d="M6.5 4.5L10 8l-3.5 3.5" />,
  "arrow-up": <path d="M8 13V3M4.5 6.5L8 3l3.5 3.5" />,
  "arrow-right": <path d="M3 8h10M9.5 4.5L13 8l-3.5 3.5" />,
  mic: (
    <>
      <rect x="6" y="2" width="4" height="7.5" rx="2" />
      <path d="M3.8 8a4.2 4.2 0 0 0 8.4 0M8 12.2V14" />
    </>
  ),
  waveform: <path d="M2.5 6.5v3M5 4v8M7.5 6v4M10 3.5v9M12.5 6.5v3" />,
  share: (
    <>
      <path d="M8 10V2.5M5 5l3-3 3 3" />
      <path d="M4 8H3v5.5h10V8h-1" />
    </>
  ),
  search: (
    <>
      <circle cx="7" cy="7" r="4" />
      <path d="M10 10l3 3" />
    </>
  ),
  "pin-angle": <path d="M9.5 2.5l4 4-2 .5-3 3-.5 2.5-4-4 2.5-.5 3-3 .5-2z" />,
  eye: (
    <>
      <path d="M1.8 8s2.3-4 6.2-4 6.2 4 6.2 4-2.3 4-6.2 4-6.2-4-6.2-4z" />
      <circle cx="8" cy="8" r="1.8" />
    </>
  ),
  "eye-off": (
    <>
      <path d="M1.8 8s2.3-4 6.2-4c1.1 0 2.1.3 3 .8M14.2 8s-2.3 4-6.2 4c-1.1 0-2.1-.3-3-.8" />
      <path d="M2.5 13.5l11-11" />
    </>
  ),
  code: <path d="M5.5 4.5L2 8l3.5 3.5M10.5 4.5L14 8l-3.5 3.5" />,
  expand: <path d="M9.5 2.5h4v4M13.5 2.5L9 7M6.5 13.5h-4v-4M2.5 13.5L7 9" />,
  "cloud-up": (
    <>
      <path d="M4.5 12.5a3 3 0 0 1-.3-6A4 4 0 0 1 12 7.6a2.5 2.5 0 0 1-.5 4.9" />
      <path d="M8 13.5V8.5M5.9 10.4L8 8.3l2.1 2.1" />
    </>
  ),
  dots: (
    <>
      <circle cx="3.5" cy="8" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="8" cy="8" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="12.5" cy="8" r="1.1" fill="currentColor" stroke="none" />
    </>
  ),
  archive: (
    <>
      <path d="M2 4.5h12V7H2z" />
      <path d="M3 7v6.5h10V7" />
      <path d="M6.5 9.5h3" />
    </>
  ),
  trash: (
    <>
      <path d="M3 4.5h10" />
      <path d="M5.5 4.5V3h5v1.5" />
      <path d="M4 4.5l.7 9h6.6l.7-9" />
    </>
  ),
  image: (
    <>
      <rect x="2.5" y="3" width="11" height="10" rx="1.5" />
      <circle cx="6" cy="6.5" r="1" />
      <path d="M3 12l3-3 2.5 2.5L11 8l2 2" />
    </>
  ),
};

export function Icon({
  name,
  size = 16,
  label,
  className,
}: {
  name: IconName;
  size?: number;
  label?: string;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      {PATHS[name]}
    </svg>
  );
}
