"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { Mail, ShieldCheck, XCircle, Clock } from "lucide-react";
import { invitesApi, isLoggedIn } from "@/lib/api-client";

interface InviteLanding {
  league_id: string;
  league_name: string;
  league_description: string | null;
  inviter_username: string;
  personal_message: string | null;
  usable: boolean;
}

export default function InviteLandingPage() {
  const params = useParams();
  const router = useRouter();
  const token = params.token as string;

  const [invite, setInvite] = useState<InviteLanding | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [accepting, setAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState("");
  const [accepted, setAccepted] = useState(false);

  const loadInvite = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const data = await invitesApi.getByToken(token);
      setInvite(data as InviteLanding);
    } catch (err) {
      // 404 (unknown token) and any other failure both land here -- the
      // landing page has nothing more specific to say either way.
      setLoadError(err instanceof Error ? err.message : "This invite link isn't valid.");
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    loadInvite();
  }, [loadInvite]);

  const handleAccept = async () => {
    setAccepting(true);
    setAcceptError("");
    try {
      const result = await invitesApi.accept(token) as { league_id: string };
      setAccepted(true);
      setTimeout(() => router.push(`/leagues/${result.league_id}`), 1500);
    } catch (err) {
      setAcceptError(err instanceof Error ? err.message : "Failed to accept invite.");
    } finally {
      setAccepting(false);
    }
  };

  const nextParam = `/invites/${token}`;

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-8">
          <div className="text-center mb-6">
            <div className="w-12 h-12 bg-gold-400 rounded-xl flex items-center justify-center mx-auto mb-4">
              <Mail className="w-6 h-6 text-surface-900" />
            </div>
            <h1 className="text-2xl font-bold text-white">League Invite</h1>
          </div>

          {loading ? (
            <div className="flex items-center justify-center gap-3 py-8">
              <div className="w-6 h-6 border-2 border-gold-400 border-t-transparent rounded-full animate-spin" />
              <span className="text-surface-400 text-sm">Loading invite...</span>
            </div>
          ) : loadError ? (
            <div className="text-center">
              <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm mb-6" role="alert">
                <XCircle className="w-5 h-5 mx-auto mb-2" />
                {loadError}
              </div>
              <Link href="/leagues" className="text-gold-400 hover:text-gold-300 font-medium text-sm">
                Browse leagues instead
              </Link>
            </div>
          ) : accepted ? (
            <div className="p-4 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400 text-sm text-center" role="status">
              <ShieldCheck className="w-5 h-5 mx-auto mb-2" />
              You&apos;re in! Taking you to the league...
            </div>
          ) : invite ? (
            <>
              <div className="bg-surface-900 border border-surface-700 rounded-xl p-4 mb-6">
                <p className="text-white font-semibold text-lg">{invite.league_name}</p>
                {invite.league_description && (
                  <p className="text-surface-400 text-sm mt-1">{invite.league_description}</p>
                )}
                <p className="text-surface-500 text-xs mt-3">
                  Invited by <span className="text-surface-300 font-medium">{invite.inviter_username}</span>
                </p>
                {invite.personal_message && (
                  <p className="text-surface-300 text-sm mt-3 italic border-l-2 border-gold-400/40 pl-3">
                    &ldquo;{invite.personal_message}&rdquo;
                  </p>
                )}
              </div>

              {!invite.usable ? (
                <div className="p-4 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-400 text-sm text-center flex flex-col items-center gap-2">
                  <Clock className="w-5 h-5" />
                  This invite has expired, been revoked, or was already used.
                  <Link href="/leagues" className="text-gold-400 hover:text-gold-300 font-medium text-sm mt-1">
                    Browse other leagues
                  </Link>
                </div>
              ) : isLoggedIn() ? (
                <>
                  {acceptError && (
                    <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm" role="alert">
                      {acceptError}
                    </div>
                  )}
                  <button
                    onClick={handleAccept}
                    disabled={accepting}
                    className="w-full bg-gold-400 hover:bg-gold-300 text-surface-900 font-bold py-2.5 rounded-lg transition-all hover:shadow-lg hover:shadow-gold-400/25 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {accepting ? "Joining..." : "Accept Invite"}
                  </button>
                </>
              ) : (
                <div className="space-y-3">
                  <p className="text-surface-400 text-sm text-center">
                    Sign in or create an account to accept this invite.
                  </p>
                  <Link
                    href={`/login?next=${encodeURIComponent(nextParam)}`}
                    className="block w-full text-center bg-gold-400 hover:bg-gold-300 text-surface-900 font-bold py-2.5 rounded-lg transition-all"
                  >
                    Sign In
                  </Link>
                  <Link
                    href={`/register?next=${encodeURIComponent(nextParam)}`}
                    className="block w-full text-center bg-surface-700 hover:bg-surface-600 text-white font-bold py-2.5 rounded-lg transition-all"
                  >
                    Create Account
                  </Link>
                </div>
              )}
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
