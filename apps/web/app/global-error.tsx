"use client";

/**
 * Last-resort boundary for errors thrown in the root layout itself.
 *
 * This replaces the whole document, so it renders its own <html>/<body> and
 * cannot rely on the app's providers, fonts, or Tailwind layer being mounted —
 * hence the inline styles.
 */

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "#0b0d12",
          color: "#e6e8ee",
          fontFamily: "system-ui, sans-serif",
          padding: "2rem",
        }}
      >
        <main style={{ maxWidth: "32rem" }}>
          <h1 style={{ fontSize: "1.5rem", marginBottom: "0.75rem" }}>StockViz is unavailable</h1>
          <p style={{ color: "#98a0b3", lineHeight: 1.6 }}>
            The application failed to start. Please try again in a moment.
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: "1.25rem",
              padding: "0.5rem 1rem",
              borderRadius: "0.375rem",
              border: "1px solid #2a3040",
              background: "#151a24",
              color: "inherit",
              cursor: "pointer",
            }}
          >
            Try again
          </button>
          {error.digest ? (
            <p style={{ marginTop: "1rem", fontSize: "0.75rem", color: "#6b7488" }}>
              Reference: {error.digest}
            </p>
          ) : null}
        </main>
      </body>
    </html>
  );
}
