import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import Header from "@/components/Header";
import Footer from "@/components/Footer";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Fantasy Football Crew | Custom Leagues, AI Analysis",
  description:
    "Build your perfect fantasy football league with fully customizable scoring, 2-Man Teams, Conference Battles, and AI-powered analysis.",
  keywords: [
    "fantasy football",
    "custom scoring",
    "fantasy football crew",
    "2 man teams",
    "conference leagues",
    "ai fantasy analysis",
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-surface-900 text-white relative">
        {/* Stadium-at-night backdrop: faint yard-line stripes + vignette, fixed behind all content */}
        <div className="stadium-backdrop fixed inset-0 pointer-events-none z-0" />
        <div className="relative z-10 flex flex-col min-h-full">
          <Header />
          <main className="flex-1">{children}</main>
          <Footer />
        </div>
      </body>
    </html>
  );
}
