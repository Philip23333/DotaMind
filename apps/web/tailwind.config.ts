import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        focus: "0 0 0 3px color-mix(in oklch, var(--color-primary) 24%, transparent)",
      },
    },
  },
  plugins: [],
};

export default config;
