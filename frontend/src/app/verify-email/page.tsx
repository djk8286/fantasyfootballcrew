"use client";

import { Suspense, useState, useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { authApi } from "@/lib/api-client";

type Status = "verifying" | "success" | "error";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  const [status, setStatus] = useState<Status>(token ? "verifying" : "error");
  const [error, setError] = useState("");
  const attempted = useRef(false);

  useEffect(() => {
    if (!token || attempted.current) return;
    attempted.current = true; // React 18 Strict Mode double-invokes effects -- a verification token is single-use, so a second attempt would otherwise always fail and show a false error.
    authApi
      .verifyEmail(token)
      .then(() => setStatus("success"))
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "This verification link is invalid or has expired.");
        setStatus("error");
      });
  }, [token]);

  if (!token) {
    return (
      <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm text-center" role="alert">
        This link is missing its verification token.
      </div>
    );
  }

  if (status === "verifying") {
    return (
      <div className="text-center text-surface-400 text-sm">
        Verifying your email...
      </div>
    );
  }

  if (status === "success") {
    return (
      <div className="text-center">
        <div className="p-4 bg-green-500/10 border border-green-500/30 rounded-lg text-green-400 text-sm mb-6" role="status">
          Your email is verified. Thanks!
        </div>
        <Link href="/dashboard" className="text-gold-400 hover:text-gold-300 font-medium text-sm">
          Continue to your dashboard
        </Link>
      </div>
    );
  }

  return (
    <div className="text-center">
      <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm mb-6" role="alert">
        {error}
      </div>
      <p className="text-surface-500 text-xs mb-4">
        Your account already works normally either way -- this is just a confirmation step.
      </p>
      <Link href="/dashboard" className="text-gold-400 hover:text-gold-300 font-medium text-sm">
        Continue to your dashboard
      </Link>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <div className="min-h-[80vh] flex items-center justify-center px-4">
      <div className="w-full max-w-md">
        <div className="bg-surface-800 border border-surface-700 rounded-2xl p-8">
          <div className="text-center mb-8">
            <div className="w-12 h-12 bg-gold-400 rounded-xl flex items-center justify-center mx-auto mb-4">
              <span className="text-surface-900 font-bold text-lg">FFC</span>
            </div>
            <h1 className="text-2xl font-bold text-white">Verify Your Email</h1>
          </div>
          <Suspense fallback={<div className="text-center text-surface-500 text-sm">Loading...</div>}>
            <VerifyEmailContent />
          </Suspense>
        </div>
      </div>
    </div>
  );
}
