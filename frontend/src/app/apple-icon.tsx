import { ImageResponse } from "next/og";

// Next.js file-convention icon -- auto-detected, wires up the
// <link rel="apple-touch-icon"> tag itself. iOS doesn't read the web
// manifest for its home-screen icon the way Android does; this is what it
// actually uses for "Add to Home Screen".
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#d4af37",
        }}
      >
        <span
          style={{
            color: "#0a0a0a",
            fontWeight: 700,
            fontSize: 76,
            letterSpacing: -2,
          }}
        >
          FFC
        </span>
      </div>
    ),
    { ...size },
  );
}
