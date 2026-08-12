"use client";

import { useEffect } from "react";

// Root-level error boundary -- only fires if the ROOT layout itself
// throws (Header/Footer/the providers around them), which error.tsx
// can't catch since it renders *inside* that same layout. Has to render
// its own <html>/<body> since it replaces the whole tree, so this is
// deliberately minimal/self-contained rather than reusing components
// that might be part of what just broke.
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backgroundColor: "#0a0a0a",
          color: "#fff",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <div style={{ textAlign: "center", padding: "0 1.5rem" }}>
          <h1 style={{ fontSize: "1.25rem", fontWeight: 700, marginBottom: "0.5rem" }}>
            Something went wrong
          </h1>
          <p style={{ color: "#9ca3af", fontSize: "0.875rem", marginBottom: "1.5rem" }}>
            The app hit an unexpected error and couldn&apos;t recover this page.
          </p>
          <button
            onClick={reset}
            style={{
              backgroundColor: "#facc15",
              color: "#0a0a0a",
              fontWeight: 600,
              fontSize: "0.875rem",
              padding: "0.625rem 1.5rem",
              borderRadius: "0.75rem",
              border: "none",
              cursor: "pointer",
            }}
          >
            Try Again
          </button>
        </div>
      </body>
    </html>
  );
}
