import type { Config } from "tailwindcss";

export default {
  content: ["./frontend/index.html", "./frontend/src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#172033",
        muted: "#647084",
        panel: "#ffffff",
        line: "#dce3ed",
        bilibili: "#fb7299",
        cyan: "#16a3b8",
        mint: "#2f9d78",
        amber: "#c98512",
      },
      boxShadow: {
        soft: "0 14px 40px rgba(23, 32, 51, 0.08)",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
      },
    },
  },
  plugins: [],
} satisfies Config;
