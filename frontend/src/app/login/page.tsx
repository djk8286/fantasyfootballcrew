"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { authApi } from "@/lib/api-client";
import RedirectIfLoggedIn from "@/components/RedirectIfLoggedIn";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Set by api-client.ts when a request comes back 401 with a token
  // attached -- i.e. the token itself was rejected (expired/invalid), not
  // just "this action needs auth." See apiRequest()'s 401 handling.
  const expired = searchParams.get("expired") === "1";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const result = await authApi.login(email, password);
      const data = result as { access_token?: string; user?: { id: string; email?: string } };
      if (data.access_token) {
        localStorage.setItem("ffc_token", data.access_token);
        localStorage.setItem("ffc_user_id", data.user?.id || "");
      }
      router.push("/dashboard");
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Invalid email or password";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {/* Error message takes priority over the session-expired notice --
          once someone's actively trying to sign in again, a fresh error
          about that attempt is more relevant than why they ended up here. */}
      {error ? (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm" role="alert">
          {error}
        </div>
      ) : expired ? (
        <div className="mb-4 p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-400 text-sm">
          Your session expired. Please sign in again.
        </div>
      ) : null}

      {/* Form */}
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
        <div>
          <div className="flex items-center justify-between mb-1.5">
            <label
              htmlFor="password"
              className="block text-sm font-medium text-surface-300"
            >
              Password
            </label>
            <Link
              href="/forgot-password"
              className="text-xs text-gold-400 hover:text-gold-300 font-medium"
            >
              Forgot password?
            </Link>
          </div>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-gold-400 focus:border-transparent transition-all"
          />
        </div>
        <button
          type="submit"
          disabled={loading}
          className="w-full bg-gold-400 hover:bg-gold-300 text-surface-900 font-bold py-2.5 rounded-lg transition-all hover:shadow-lg hover:shadow-gold-400/25 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? "Signing In..." : "Sign In"}
        </button>
      </form>

      {/* Register Link */}
      <p className="text-center text-surface-400 text-sm mt-6">
        Don&apos;t have an account?{" "}
        <Link
          href="/register"
          className="text-gold-400 hover:text-gold-300 font-medium"
        >
          Sign up
        </Link>
      </p>
    </>
  );
}

export default function LoginPage() {
  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4">
      <RedirectIfLoggedIn />
      <div className="w-full max-w-md">
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-8">
          {/* Header */}
          <div className="text-center mb-8">
            <div className="w-12 h-12 bg-gold-400 rounded-xl flex items-center justify-center mx-auto mb-4">
              <span className="text-surface-900 font-bold text-lg">FFC</span>
            </div>
            <h1 className="text-2xl font-bold text-white">Welcome Back</h1>
            <p className="text-surface-400 text-sm mt-1">
              Sign in to manage your leagues
            </p>
          </div>

          <Suspense fallback={<div className="text-center text-surface-500 text-sm">Loading...</div>}>
            <LoginForm />
          </Suspense>
        </div>
      </div>
    </div>
  );
}
