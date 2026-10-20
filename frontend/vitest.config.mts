import { defineConfig } from "vitest/config";

export default defineConfig({
  // Vite 8 transforms with oxc (esbuild is gone); automatic runtime so .tsx tests don't need `import React`.
  oxc: { jsx: { runtime: "automatic" } },
  test: { environment: "node", include: ["src/**/*.test.{ts,tsx}"] },
});
