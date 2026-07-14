import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* Production-optimized config for Vercel */
  trailingSlash: false,
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "**.sleeper.com",
      },
    ],
  },
  // Output standalone for Vercel
  output: "standalone",
};

export default nextConfig;