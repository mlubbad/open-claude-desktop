import { Component, type ErrorInfo, type ReactNode } from "react";

// Top-level safety net. The whole UI mounts under one React root, so a render-time
// throw anywhere below would unmount the entire tree and leave a blank white window
// with no way back except force-quitting. This boundary catches that, shows a
// recoverable message, and offers a reload — turning a dead screen into a hiccup.
//
// Styles are inline on purpose: if the failure was in the stylesheet/theme layer, a
// class-based fallback could itself render invisibly. This one always shows.
export class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Surface for diagnosis (dev console / packaged log). No telemetry is sent.
    console.error("Unhandled UI error:", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div
        role="alert"
        style={{
          maxWidth: 560,
          margin: "10vh auto",
          padding: "2rem",
          fontFamily: "system-ui, -apple-system, sans-serif",
          lineHeight: 1.5,
        }}
      >
        <h1 style={{ fontSize: "1.35rem", margin: "0 0 .5rem" }}>Something went wrong</h1>
        <p style={{ opacity: 0.8, margin: "0 0 1rem" }}>
          The app hit an unexpected error. Your saved chats are safe on disk — reloading
          usually clears it.
        </p>
        <pre
          style={{
            whiteSpace: "pre-wrap",
            background: "rgba(128,128,128,.14)",
            padding: ".75rem",
            borderRadius: 8,
            fontSize: ".85rem",
            overflowX: "auto",
            margin: 0,
          }}
        >
          {error.message || String(error)}
        </pre>
        <button
          onClick={() => window.location.reload()}
          style={{
            marginTop: "1rem",
            padding: ".5rem 1.1rem",
            borderRadius: 8,
            border: "1px solid currentColor",
            background: "transparent",
            color: "inherit",
            font: "inherit",
            cursor: "pointer",
          }}
        >
          Reload
        </button>
      </div>
    );
  }
}
