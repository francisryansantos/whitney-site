// @ts-check
import { defineConfig } from "astro/config";

export default defineConfig({
  site: "https://example.com", // replace when deployed
  trailingSlash: "ignore",
  build: { format: "directory" },
  vite: {
    build: {
      rollupOptions: {
        // Pagefind ships its own JS into dist/_pagefind/ at the end of the
        // build (after astro). Don't try to resolve it during the bundle.
        external: ["/_pagefind/pagefind.js"],
      },
    },
  },
});
