"use client";

import { getAvatarStyle } from "@/lib/team-avatars";

// avatar_url holds one of two shapes: "ffc-avatar:<id>" (the built-in
// icon set) or "data:image/...;base64,..." (a real uploaded photo, from
// AvatarEditor's canvas resize). Anything else (http(s) URL) is treated
// as a real image too, in case a future upload path ever hosts these
// externally instead of inlining them.
function isPhoto(url: string | null | undefined): url is string {
  return !!url && (url.startsWith("data:image/") || url.startsWith("http://") || url.startsWith("https://"));
}

export default function Avatar({
  url,
  size = 36,
  rounded = "rounded-xl",
  className = "",
  title,
}: {
  url: string | null | undefined;
  size?: number;
  rounded?: string;
  className?: string;
  title?: string;
}) {
  // No default border baked in here -- callers want different ones (a
  // subtle outline in a table row vs. a thick surface-colored ring to
  // separate overlapping circles in a stack), so it's on `className`
  // instead of fighting a hardcoded default for the same CSS property.
  if (isPhoto(url)) {
    // eslint-disable-next-line @next/next/no-img-element -- these are
    // data: URIs (or, later, arbitrary hosts) that next/image's
    // optimizer can't process; a plain <img> is the correct tool here.
    return (
      <img
        src={url}
        alt=""
        title={title}
        width={size}
        height={size}
        style={{ width: size, height: size }}
        className={`${rounded} object-cover shrink-0 ${className}`}
      />
    );
  }
  const { bg, icon } = getAvatarStyle(url ?? null);
  return (
    <div
      title={title}
      style={{ width: size, height: size, backgroundColor: bg, fontSize: Math.round(size * 0.5) }}
      className={`${rounded} flex items-center justify-center shrink-0 ${className}`}
    >
      {icon}
    </div>
  );
}

export { isPhoto };
