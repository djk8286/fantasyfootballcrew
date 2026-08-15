"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { usersApi, logout } from "@/lib/api-client";
import { useFocusTrap } from "@/lib/useFocusTrap";
import { ArrowLeft, Save, Loader2, Check, User as UserIcon, KeyRound, Mail, Calendar, AlertTriangle, X, Trash2 } from "lucide-react";

interface Me {
  id: string;
  email: string;
  username: string;
  avatar_url: string | null;
  provider: string;
  created_at: string;
}

export default function SettingsPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const [username, setUsername] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileSaved, setProfileSaved] = useState(false);
  const [profileError, setProfileError] = useState("");

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [passwordSaved, setPasswordSaved] = useState(false);
  const [passwordError, setPasswordError] = useState("");

  const [showDeleteModal, setShowDeleteModal] = useState(false);

  useEffect(() => {
    usersApi.me()
      .then((data) => {
        const user = data as Me;
        setMe(user);
        setUsername(user.username);
      })
      .catch(() => setProfileError("Failed to load your account."))
      .finally(() => setLoading(false));
  }, []);

  const handleSaveProfile = async () => {
    if (!me || username.trim() === me.username) return;
    setSavingProfile(true);
    setProfileError("");
    try {
      const updated = await usersApi.update(username.trim()) as Me;
      setMe(updated);
      setUsername(updated.username);
      setProfileSaved(true);
      setTimeout(() => setProfileSaved(false), 3000);
    } catch (err: unknown) {
      setProfileError(err instanceof Error ? err.message.replace(/^API error: \d+ ?\w* ?—? ?/, "") : "Failed to save");
    } finally {
      setSavingProfile(false);
    }
  };

  const handleChangePassword = async () => {
    setPasswordError("");
    if (newPassword.length < 8) {
      setPasswordError("New password must be at least 8 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("New passwords don't match.");
      return;
    }
    setSavingPassword(true);
    try {
      await usersApi.changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordSaved(true);
      setTimeout(() => setPasswordSaved(false), 3000);
    } catch (err: unknown) {
      setPasswordError(err instanceof Error ? err.message.replace(/^API error: \d+ ?\w* ?—? ?/, "") : "Failed to change password");
    } finally {
      setSavingPassword(false);
    }
  };

  function DeleteAccountModal({ requiresPassword, onClose }: { requiresPassword: boolean; onClose: () => void }) {
    const dialogRef = useFocusTrap<HTMLDivElement>(onClose);
    const [password, setPassword] = useState("");
    const [confirmText, setConfirmText] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState("");

    const canSubmit = confirmText === "DELETE" && (!requiresPassword || password.length > 0) && !busy;

    const handleDelete = async () => {
      if (!canSubmit) return;
      setBusy(true);
      setError("");
      try {
        await usersApi.deleteAccount(requiresPassword ? password : undefined);
        logout();
        router.push("/");
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message.replace(/^API error: \d+ ?\w* ?—? ?/, "") : "Failed to delete account");
        setBusy(false);
      }
    };

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4">
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-labelledby="delete-account-title"
          tabIndex={-1}
          className="bg-surface-800 border border-red-500/30 rounded-2xl p-6 max-w-md w-full shadow-2xl"
        >
          <div className="flex items-center justify-between mb-4">
            <h3 id="delete-account-title" className="text-lg font-semibold text-white flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-red-400" /> Delete Account
            </h3>
            <button onClick={onClose} className="text-surface-400 hover:text-white transition-colors" aria-label="Close">
              <X className="w-5 h-5" />
            </button>
          </div>

          <p className="text-surface-300 text-sm mb-4">
            This permanently deletes your account. Leagues you commissioned are transferred to
            another real member (or you'll be asked to handle that first if you're the only one
            left); your teams become CPU-controlled so those leagues keep working for everyone
            else. This can't be undone.
          </p>

          {requiresPassword && (
            <div className="mb-4">
              <label htmlFor="delete-confirm-password" className="text-xs text-surface-400 font-medium">Confirm your password</label>
              <input
                id="delete-confirm-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                className="mt-1.5 w-full px-3.5 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-red-400"
              />
            </div>
          )}

          <div className="mb-4">
            <label htmlFor="delete-confirm-text" className="text-xs text-surface-400 font-medium">
              Type <span className="font-mono text-red-400">DELETE</span> to confirm
            </label>
            <input
              id="delete-confirm-text"
              type="text"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="mt-1.5 w-full px-3.5 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-red-400"
            />
          </div>

          {error && (
            <div className="p-2.5 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-xs mb-4">{error}</div>
          )}

          <div className="flex justify-end gap-2">
            <button
              onClick={onClose}
              disabled={busy}
              className="px-4 py-2 rounded-lg text-xs font-bold text-surface-300 hover:text-white transition-colors disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              onClick={handleDelete}
              disabled={!canSubmit}
              className="inline-flex items-center gap-1.5 px-5 py-2 rounded-lg text-xs font-bold bg-red-500 hover:bg-red-400 text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {busy ? <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Deleting...</> : <><Trash2 className="w-3.5 h-3.5" /> Delete My Account</>}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-surface-400">Loading account...</span>
        </div>
      </div>
    );
  }

  if (!me) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <div className="text-center max-w-md px-4">
          <p className="text-surface-400 text-sm mb-4">{profileError || "You need to be logged in to view this page."}</p>
          <Link href="/login" className="text-gold-400 hover:text-gold-300 text-sm font-medium">
            Log in
          </Link>
        </div>
      </div>
    );
  }

  const usernameChanged = username.trim() !== "" && username.trim() !== me.username;

  return (
    <div className="min-h-screen bg-surface-900">
      <div className="sticky top-0 z-40 bg-surface-900/95 backdrop-blur-md border-b border-surface-700">
        <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-3">
          <div className="flex items-center gap-3">
            <Link href="/dashboard" aria-label="Back to dashboard" className="text-surface-400 hover:text-white transition-colors shrink-0">
              <ArrowLeft className="w-5 h-5" />
            </Link>
            <h1 className="text-lg font-bold text-white">Account Settings</h1>
          </div>
        </div>
      </div>

      <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {/* Profile */}
        <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
          <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700 flex items-center gap-2">
            <UserIcon className="w-4 h-4 text-gold-400" />
            <h3 className="text-white font-bold text-sm">Profile</h3>
          </div>
          <div className="p-5 space-y-4">
            <div>
              <label htmlFor="username" className="text-xs text-surface-400 font-medium">Username</label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => { setUsername(e.target.value); setProfileSaved(false); }}
                className="mt-1.5 w-full px-3.5 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
              />
            </div>

            <div className="flex items-center gap-2 text-surface-400 text-sm">
              <Mail className="w-3.5 h-3.5 shrink-0" />
              <span>{me.email}</span>
              <span className="text-surface-500 text-xs">(can't be changed here)</span>
            </div>

            <div className="flex items-center gap-2 text-surface-500 text-xs">
              <Calendar className="w-3.5 h-3.5 shrink-0" />
              <span>
                Member since {new Date(me.created_at).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" })}
              </span>
              <span className="ml-1 px-2 py-0.5 rounded-full bg-surface-700 text-surface-300 text-[10px] font-semibold uppercase tracking-wide">
                {me.provider}
              </span>
            </div>

            {profileError && (
              <div className="p-2.5 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-xs">{profileError}</div>
            )}

            <div className="flex justify-end">
              <button
                onClick={handleSaveProfile}
                disabled={savingProfile || !usernameChanged}
                className={`inline-flex items-center gap-1.5 px-5 py-2 rounded-lg text-xs font-bold transition-all ${
                  profileSaved ? "bg-green-500 text-white" : "bg-gold-400 hover:bg-gold-300 text-surface-900 disabled:opacity-40 disabled:cursor-not-allowed"
                }`}
              >
                {savingProfile ? (
                  <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Saving...</>
                ) : profileSaved ? (
                  <><Check className="w-3.5 h-3.5" /> Saved!</>
                ) : (
                  <><Save className="w-3.5 h-3.5" /> Save</>
                )}
              </button>
            </div>
          </div>
        </div>

        {/* Password */}
        {me.provider === "email" ? (
          <div className="bg-surface-800/60 border border-surface-700 rounded-2xl overflow-hidden">
            <div className="px-5 py-3.5 bg-surface-800 border-b border-surface-700 flex items-center gap-2">
              <KeyRound className="w-4 h-4 text-gold-400" />
              <h3 className="text-white font-bold text-sm">Change Password</h3>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label htmlFor="current-password" className="text-xs text-surface-400 font-medium">Current password</label>
                <input
                  id="current-password"
                  type="password"
                  value={currentPassword}
                  onChange={(e) => { setCurrentPassword(e.target.value); setPasswordSaved(false); }}
                  autoComplete="current-password"
                  className="mt-1.5 w-full px-3.5 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
                />
              </div>
              <div>
                <label htmlFor="new-password" className="text-xs text-surface-400 font-medium">New password</label>
                <input
                  id="new-password"
                  type="password"
                  value={newPassword}
                  onChange={(e) => { setNewPassword(e.target.value); setPasswordSaved(false); }}
                  autoComplete="new-password"
                  className="mt-1.5 w-full px-3.5 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
                />
                <p className="text-[11px] text-surface-500 mt-1">At least 8 characters.</p>
              </div>
              <div>
                <label htmlFor="confirm-new-password" className="text-xs text-surface-400 font-medium">Confirm new password</label>
                <input
                  id="confirm-new-password"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => { setConfirmPassword(e.target.value); setPasswordSaved(false); }}
                  autoComplete="new-password"
                  className="mt-1.5 w-full px-3.5 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
                />
              </div>

              {passwordError && (
                <div className="p-2.5 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-xs">{passwordError}</div>
              )}

              <div className="flex justify-end">
                <button
                  onClick={handleChangePassword}
                  disabled={savingPassword || !currentPassword || !newPassword || !confirmPassword}
                  className={`inline-flex items-center gap-1.5 px-5 py-2 rounded-lg text-xs font-bold transition-all ${
                    passwordSaved ? "bg-green-500 text-white" : "bg-gold-400 hover:bg-gold-300 text-surface-900 disabled:opacity-40 disabled:cursor-not-allowed"
                  }`}
                >
                  {savingPassword ? (
                    <><Loader2 className="w-3.5 h-3.5 animate-spin" /> Updating...</>
                  ) : passwordSaved ? (
                    <><Check className="w-3.5 h-3.5" /> Updated!</>
                  ) : (
                    <><KeyRound className="w-3.5 h-3.5" /> Update Password</>
                  )}
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="bg-surface-800/60 border border-surface-700 rounded-2xl p-5">
            <p className="text-surface-400 text-sm">
              This account signed up with {me.provider} and doesn't have a password to change here.
            </p>
          </div>
        )}

        {/* Danger Zone */}
        <div className="bg-surface-800/60 border border-red-500/20 rounded-2xl overflow-hidden">
          <div className="px-5 py-3.5 bg-red-500/5 border-b border-red-500/20 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-red-400" />
            <h3 className="text-white font-bold text-sm">Danger Zone</h3>
          </div>
          <div className="p-5 flex items-center justify-between gap-4">
            <div>
              <p className="text-white text-sm font-semibold">Delete Account</p>
              <p className="text-surface-400 text-xs mt-0.5">Permanently delete your account and all associated data. This cannot be undone.</p>
            </div>
            <button
              onClick={() => setShowDeleteModal(true)}
              className="shrink-0 inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-bold text-red-400 border border-red-500/30 hover:bg-red-500/10 transition-colors"
            >
              <Trash2 className="w-3.5 h-3.5" /> Delete Account
            </button>
          </div>
        </div>
      </div>

      {showDeleteModal && (
        <DeleteAccountModal requiresPassword={me.provider === "email"} onClose={() => setShowDeleteModal(false)} />
      )}
    </div>
  );
}
