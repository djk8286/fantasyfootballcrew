"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usersApi } from "@/lib/api-client";
import { ArrowLeft, Save, Loader2, Check, User as UserIcon, KeyRound, Mail, Calendar } from "lucide-react";

interface Me {
  id: string;
  email: string;
  username: string;
  avatar_url: string | null;
  provider: string;
  created_at: string;
}

export default function SettingsPage() {
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
            <Link href="/dashboard" className="text-surface-400 hover:text-white transition-colors shrink-0">
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
              <label className="text-xs text-surface-400 font-medium">Username</label>
              <input
                type="text"
                value={username}
                onChange={(e) => { setUsername(e.target.value); setProfileSaved(false); }}
                className="mt-1.5 w-full px-3.5 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
              />
            </div>

            <div className="flex items-center gap-2 text-surface-400 text-sm">
              <Mail className="w-3.5 h-3.5 shrink-0" />
              <span>{me.email}</span>
              <span className="text-surface-600 text-xs">(can't be changed here)</span>
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
                <label className="text-xs text-surface-400 font-medium">Current password</label>
                <input
                  type="password"
                  value={currentPassword}
                  onChange={(e) => { setCurrentPassword(e.target.value); setPasswordSaved(false); }}
                  autoComplete="current-password"
                  className="mt-1.5 w-full px-3.5 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
                />
              </div>
              <div>
                <label className="text-xs text-surface-400 font-medium">New password</label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => { setNewPassword(e.target.value); setPasswordSaved(false); }}
                  autoComplete="new-password"
                  className="mt-1.5 w-full px-3.5 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white text-sm focus:outline-none focus:ring-1 focus:ring-gold-400"
                />
                <p className="text-[11px] text-surface-500 mt-1">At least 8 characters.</p>
              </div>
              <div>
                <label className="text-xs text-surface-400 font-medium">Confirm new password</label>
                <input
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
      </div>
    </div>
  );
}
