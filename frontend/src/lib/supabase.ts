import { createClient } from "@supabase/supabase-js";

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

export const supabase = createClient(supabaseUrl, supabaseAnonKey);

// Placeholder auth helper — replace with Supabase auth when configured
export async function signInWithEmail(email: string, password: string) {
  const backendUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
  const res = await fetch(`${backendUrl}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  return res.json();
}

export async function signUpWithEmail(
  email: string,
  username: string,
  password: string
) {
  const backendUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";
  const res = await fetch(`${backendUrl}/api/v1/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, username, password, provider: "email" }),
  });
  return res.json();
}

export async function signInWithGoogle() {
  // Placeholder — will use Supabase Google OAuth
  console.log("Google sign-in coming when Supabase is configured");
}
