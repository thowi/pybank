import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dev server proxies /api to `pybank-import review-ui`. The build goes
// into the Python package, which serves it.
export default defineConfig({
  build: { emptyOutDir: true, outDir: "../src/pybank/web/static" },
  // React Compiler memoizes components and hooks. Target 18 for React 18.
  plugins: [
    react({
      babel: { plugins: [["babel-plugin-react-compiler", { target: "18" }]] },
    }),
  ],
  server: { proxy: { "/api": "http://127.0.0.1:8780" } },
});
