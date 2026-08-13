"use client";

import { useState } from "react";
import Link from "next/link";
import { authApi } from "@/lib/api-client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await authApi.forgotPassword(email);
      // Same confirmation regardless of whether the email is registered --
      // the backend already returns an identical response either way, so
      // there's nothing more specific to show here even on success.
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-8">
          <div className="text-center mb-8">
            <div className="w-12 h-12 bg-gold-400 rounded-xl flex items-center justify-center mx-auto mb-4">
              <span className="text-surface-900 font-bold text-lg">FFC</span>
            </div>
            <h1 className="text-2xl font-bold text-white">Reset Your Password</h1>
            <p className="text-surface-400 text-sm mt-1">
              Enter your email and we&apos;ll send you a reset link
            </p>
          </div>

          {submitted ? (
            <div className="text-center">
              <div className="p-4 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400 text-sm mb-6">
                If that email is registered, a password reset link has been sent. It expires in 1 hour.
              </div>
              <Link
                href="/login"
                className="text-gold-400 hover:text-gold-300 font-medium text-sm"
              >
                Back to sign in
              </Link>
            </div>
          ) : (
            <>
              {error && (
                <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm" role="alert">
                  {error}
                </div>
              )}
              <form className="space-y-4" onSubmit={handleSubmit}>
                <div>
                  <label
                    htmlFor="email"
                    className="block text-sm font-medium text-surface-300 mb-1.5"
                  >
                    Email
                  </label>
                  <input
                    id="email"
                    type="email"
                    required
                    placeholder="you@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-gold-400 focus:border-transparent transition-all"
                  />
                </div>
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full bg-gold-400 hover:bg-gold-300 text-surface-900 font-bold py-2.5 rounded-lg transition-all hover:shadow-lg hover:shadow-gold-400/25 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {loading ? "Sending..." : "Send Reset Link"}
                </button>
              </form>
              <p className="text-center text-surface-400 text-sm mt-6">
                Remembered it?{" "}
                <Link href="/login" className="text-gold-400 hover:text-gold-300 font-medium">
                  Sign in
                </Link>
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
