import { ImageResponse } from "next/og";

// PWA manifest icons (192, 512, and a maskable 512), generated at request
// time from JSX/CSS instead of shipping binary assets -- there was no
// existing FantasyFootballCrew logo file anywhere in the repo to rasterize,
// just the inline gold-square "FFC" mark in Header.tsx. This reproduces
// that same mark (#d4af37 on #0a0a0a, from globals.css) at each size Next
// needs for app/manifest.ts.
//
// The maskable variant has no rounded corners and a smaller glyph: Android
// applies its own shape mask (circle, squircle, rounded-square depending on
// OEM) to maskable icons, safe content needs to stay within the center
// ~80% or corners/edges get clipped -- see
// https://developer.chrome.com/blog/maskable-icon.

const SUPPORTED_SIZES = [192, 512];

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ size: string }> },
) {
  const { size: sizeParam } = await params;
  const maskable = sizeParam.endsWith("-maskable");
  const size = parseInt(maskable ? sizeParam.slice(0, -"-maskable".length) : sizeParam, 10);

  if (!SUPPORTED_SIZES.includes(size)) {
    return new Response("Not found", { status: 404 });
  }

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
          borderRadius: maskable ? 0 : size * 0.22,
        }}
      >
        <span
          style={{
            color: "#0a0a0a",
            fontWeight: 700,
            fontSize: size * (maskable ? 0.3 : 0.42),
            letterSpacing: -size * 0.01,
          }}
        >
          FFC
        </span>
      </div>
    ),
    { width: size, height: size },
  );
}
