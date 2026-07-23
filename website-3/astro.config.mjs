import { defineConfig } from "astro/config";
import react from "@astrojs/react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  site: "https://novaguard.fun",
  integrations: [react()],
  // Hide the floating Astro dev toolbar (the A + tools widget in the corner).
  devToolbar: { enabled: false },
  vite: { plugins: [tailwindcss()] },
});
