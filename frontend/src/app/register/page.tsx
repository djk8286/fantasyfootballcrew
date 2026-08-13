"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { authApi } from "@/lib/api-client";
import RedirectIfLoggedIn from "@/components/RedirectIfLoggedIn";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    firstName: "",
    lastName: "",
    email: "",
    username: "",
    password: "",
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => ({ ...prev, [e.target.id]: e.target.value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const result = await authApi.register(
        form.email,
        form.username,
        form.password
      );
      // Auto-login after registration
      const loginResult = await authApi.login(form.email, form.password);
      const loginData = loginResult as { access_token?: string; user?: { id: string; email?: string } };
      if (loginData.access_token) {
        localStorage.setItem("ffc_token", loginData.access_token);
        localStorage.setItem("ffc_user_id", loginData.user?.id || "");
      }
      router.push("/dashboard");
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "Something went wrong";
      setError(message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4 py-12">
      <RedirectIfLoggedIn />
      <div className="w-full max-w-md">
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-8">
          {/* Header */}
          <div className="text-center mb-8">
            <div className="w-12 h-12 bg-gold-400 rounded-xl flex items-center justify-center mx-auto mb-4">
              <span className="text-surface-900 font-bold text-lg">FFC</span>
            </div>
            <h1 className="text-2xl font-bold text-white">
              Join FantasyFootballCrew
            </h1>
            <p className="text-surface-400 text-sm mt-1">
              Create your account and start building
            </p>
          </div>

          {/* Error Message */}
          {error && (
            <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm" role="alert">
              {error}
            </div>
          )}

          {/* Form */}
          <form className="space-y-4" onSubmit={handleSubmit}>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="firstName"
                  className="block text-sm font-medium text-surface-300 mb-1.5"
                >
                  First Name
                </label>
                <input
                  id="firstName"
                  type="text"
                  placeholder="John"
                  value={form.firstName}
                  onChange={handleChange}
                  className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-gold-400 focus:border-transparent transition-all"
                />
              </div>
              <div>
                <label
                  htmlFor="lastName"
                  className="block text-sm font-medium text-surface-300 mb-1.5"
                >
                  Last Name
                </label>
                <input
                  id="lastName"
                  type="text"
                  placeholder="Doe"
                  value={form.lastName}
                  onChange={handleChange}
                  className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-gold-400 focus:border-transparent transition-all"
                />
              </div>
            </div>
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
                value={form.email}
                onChange={handleChange}
                className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-gold-400 focus:border-transparent transition-all"
              />
            </div>
            <div>
              <label
                htmlFor="username"
                className="block text-sm font-medium text-surface-300 mb-1.5"
              >
                Username
              </label>
              <input
                id="username"
                type="text"
                required
                placeholder="footballfan23"
                value={form.username}
                onChange={handleChange}
                className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-gold-400 focus:border-transparent transition-all"
              />
            </div>
            <div>
              <label
                htmlFor="password"
                className="block text-sm font-medium text-surface-300 mb-1.5"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                autoComplete="new-password"
                required
                placeholder="Create a strong password"
                value={form.password}
                onChange={handleChange}
                className="w-full px-4 py-2.5 bg-surface-900 border border-surface-600 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-gold-400 focus:border-transparent transition-all"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full bg-gold-400 hover:bg-gold-300 text-surface-900 font-bold py-2.5 rounded-lg transition-all hover:shadow-lg hover:shadow-gold-400/25 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? "Creating Account..." : "Create Account"}
            </button>
          </form>

          {/* Login Link */}
          <p className="text-center text-surface-400 text-sm mt-6">
            Already have an account?{" "}
            <Link
              href="/login"
              className="text-gold-400 hover:text-gold-300 font-medium"
            >
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
