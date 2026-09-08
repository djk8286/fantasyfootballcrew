"use client";

import { useRef, useState } from "react";
import { X, Upload, Loader2 } from "lucide-react";
import { TEAM_AVATARS, AVATAR_URL_PREFIX } from "@/lib/team-avatars";
import { useFocusTrap } from "@/lib/useFocusTrap";
import Avatar from "./Avatar";

const MAX_SOURCE_FILE_BYTES = 10 * 1024 * 1024; // 10MB -- rejected before we ever touch canvas/FileReader on it
const OUTPUT_DIMENSION = 256; // square, matches this component everywhere it's used
const OUTPUT_QUALITY = 0.85; // JPEG quality -- a 256x256 photo at this quality is typically 15-40KB

// Center-crops to a square (so a landscape or portrait photo doesn't get
// squished) then downsizes to a small fixed size -- keeps every uploaded
// avatar in the same tens-of-KB range regardless of source resolution,
// well under the backend's validate_avatar_url cap.
function processImageFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!file.type.startsWith("image/")) {
      reject(new Error("That's not an image file."));
      return;
    }
    if (file.size > MAX_SOURCE_FILE_BYTES) {
      reject(new Error("That image is too large (max 10MB)."));
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Couldn't read that file."));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("That doesn't look like a valid image."));
      img.onload = () => {
        const side = Math.min(img.width, img.height);
        const sx = (img.width - side) / 2;
        const sy = (img.height - side) / 2;
        const canvas = document.createElement("canvas");
        canvas.width = OUTPUT_DIMENSION;
        canvas.height = OUTPUT_DIMENSION;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          reject(new Error("Image editing isn't supported in this browser."));
          return;
        }
        ctx.drawImage(img, sx, sy, side, side, 0, 0, OUTPUT_DIMENSION, OUTPUT_DIMENSION);
        resolve(canvas.toDataURL("image/jpeg", OUTPUT_QUALITY));
      };
      img.src = reader.result as string;
    };
    reader.readAsDataURL(file);
  });
}

export default function AvatarEditor({
  title,
  currentUrl,
  onSave,
  onClose,
}: {
  title: string;
  currentUrl: string | null;
  onSave: (url: string) => Promise<void>;
  onClose: () => void;
}) {
  const dialogRef = useFocusTrap<HTMLDivElement>(onClose);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [tab, setTab] = useState<"upload" | "icon">("upload");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const currentIconId = currentUrl?.startsWith(AVATAR_URL_PREFIX) ? currentUrl.replace(AVATAR_URL_PREFIX, "") : "";

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file later
    if (!file) return;
    setError("");
    setBusy(true);
    try {
      const dataUrl = await processImageFile(file);
      await onSave(dataUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to process that image.");
    } finally {
      setBusy(false);
    }
  };

  const handlePickIcon = async (avatarId: string) => {
    setError("");
    setBusy(true);
    try {
      await onSave(`${AVATAR_URL_PREFIX}${avatarId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update avatar.");
    } finally {
      setBusy(false);
    }
  };

  const handleRemove = async () => {
    setError("");
    setBusy(true);
    try {
      await onSave("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove avatar.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="avatar-editor-title"
        tabIndex={-1}
        className="bg-surface-800 border border-surface-700 rounded-2xl p-6 max-w-lg w-full shadow-2xl"
      >
        <div className="flex items-center justify-between mb-5">
          <h3 id="avatar-editor-title" className="text-lg font-semibold text-white">{title}</h3>
          <button onClick={onClose} className="text-surface-400 hover:text-white transition-colors" aria-label="Close">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="flex items-center gap-1 mb-5 p-1 bg-surface-900 border border-surface-700 rounded-lg w-fit">
          <button
            onClick={() => setTab("upload")}
            className={`px-3.5 py-1.5 rounded-md text-xs font-bold transition-colors ${
              tab === "upload" ? "bg-gold-400 text-surface-900" : "text-surface-400 hover:text-white"
            }`}
          >
            Upload Photo
          </button>
          <button
            onClick={() => setTab("icon")}
            className={`px-3.5 py-1.5 rounded-md text-xs font-bold transition-colors ${
              tab === "icon" ? "bg-gold-400 text-surface-900" : "text-surface-400 hover:text-white"
            }`}
          >
            Choose Icon
          </button>
        </div>

        {tab === "upload" ? (
          <div className="flex flex-col items-center gap-4">
            <Avatar url={currentUrl} size={96} className="border border-surface-700/50" />
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              onChange={handleFileChange}
              className="hidden"
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={busy}
              className="inline-flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-bold bg-gold-400 hover:bg-gold-300 text-surface-900 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {busy ? <><Loader2 className="w-4 h-4 animate-spin" /> Processing...</> : <><Upload className="w-4 h-4" /> Choose a Photo</>}
            </button>
            <p className="text-surface-500 text-xs text-center">JPG, PNG, or GIF. Automatically cropped to a square.</p>
          </div>
        ) : (
          <div className="grid grid-cols-5 gap-3">
            {TEAM_AVATARS.map((av) => (
              <button
                key={av.id}
                onClick={() => handlePickIcon(av.id)}
                disabled={busy}
                className={`w-full aspect-square rounded-xl flex items-center justify-center text-2xl transition-all hover:scale-110 hover:shadow-lg disabled:opacity-50 ${
                  currentIconId === av.id
                    ? "ring-2 ring-gold-400 ring-offset-2 ring-offset-surface-800 scale-110"
                    : "border border-surface-600 hover:border-gold-400/50"
                }`}
                style={{ backgroundColor: av.bg }}
                title={av.label}
              >
                {av.icon}
              </button>
            ))}
          </div>
        )}

        {error && (
          <div className="mt-4 p-2.5 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-xs">{error}</div>
        )}

        {currentUrl && (
          <button
            onClick={handleRemove}
            disabled={busy}
            className="mt-4 w-full text-sm text-surface-400 hover:text-red-400 transition-colors disabled:opacity-50"
          >
            Remove avatar
          </button>
        )}
      </div>
    </div>
  );
}
