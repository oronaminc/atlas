/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: { "2xl": "1400px" },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        // Severity / status — opacity-modifier friendly (<alpha-value>) so
        // tinted fills like `bg-severity-critical/10` work. Always paired
        // with a per-severity icon (●/▲/■) for colorblind-safety.
        severity: {
          critical: "hsl(var(--sev-critical) / <alpha-value>)",
          warning: "hsl(var(--sev-warning) / <alpha-value>)",
          info: "hsl(var(--sev-info) / <alpha-value>)",
        },
        status: {
          ok: "hsl(var(--sev-ok) / <alpha-value>)",
          pending: "hsl(var(--sev-warning) / <alpha-value>)",
          failed: "hsl(var(--sev-critical) / <alpha-value>)",
          dead: "hsl(var(--sev-critical) / <alpha-value>)",
          neutral: "hsl(var(--sev-neutral) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: [
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Noto Sans KR",
          "Apple SD Gothic Neo",
          "sans-serif",
        ],
      },
      boxShadow: {
        // Soft card elevation — separation by gentle shadow, not hard borders.
        card: "0 1px 2px 0 hsl(220 30% 18% / 0.04), 0 1px 3px 0 hsl(220 30% 18% / 0.06)",
      },
      borderRadius: {
        xl: "calc(var(--radius) + 4px)",
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
