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
        // Brand tones live under the same names the UI already uses. Defining a flat string
        // replaced Tailwind's whole scale, so bg-cyan-50 / text-amber-700 were never generated;
        // keep DEFAULT for the bare classes and provide the tint keys the UI actually uses.
        cyan: {
          50: "#ecfbfd",
          100: "#d0f3f8",
          700: "#0e6f7f",
          DEFAULT: "#16a3b8",
        },
        mint: "#2f9d78",
        amber: {
          50: "#fff8e8",
          100: "#fdecc8",
          200: "#f8d995",
          300: "#f0bd5c",
          500: "#d99a25",
          600: "#c98512",
          700: "#a86a0c",
          800: "#85530a",
          900: "#613c08",
          DEFAULT: "#c98512",
        },
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
