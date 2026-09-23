/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  // Class-based dark mode. The `<html>` element gets `class="dark"` when the
  // user opts into dark via the theme toggle (see lib/theme.ts). Default is
  // light, NotebookLM-style.
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // ── Semantic palette wired to CSS variables ─────────────────────────
        // Variables live in `index.css` under `:root` (light) and `.dark`
        // (dark) so every `bg-paper-*` / `text-ink-*` callsite in the app
        // gets the right value automatically. The `<alpha-value>` pattern
        // lets Tailwind's `/30`, `/15`, etc. opacity modifiers keep working.
        paper: {
          DEFAULT: "rgb(var(--paper) / <alpha-value>)",      // primary surface — panels, page bg
          dark:    "rgb(var(--paper-dark) / <alpha-value>)", // base — body, deepest layer
          light:   "rgb(var(--paper-light) / <alpha-value>)",// elevated — cards, hover targets
          lighter: "rgb(var(--paper-lighter) / <alpha-value>)",// top — modals, popovers
        },
        ink: {
          // Tokens semánticos para texto + borders. La intención es:
          //   `ink`        → primary text (body)
          //   `ink-muted`  → secondary text (labels, helpers)
          //   `ink-faint`  → tertiary text (captions, microcopy)
          //   `ink-dim`    → borders y dividers
          //
          // Convención (auditoría P2 #19, 2026-05-25 — reforzada
          // M32 2026-05-26): cada uno se usa sin opacidad
          // (`text-ink-muted`, no `text-ink-muted/70`).
          //
          // Para borders, hay dos niveles intencionales:
          //   `border-ink-dim/60` → border visible (panels, cards)
          //   `border-ink-dim/30` → divider sutil (rows, separators)
          // CUALQUIER OTRO valor (/40, /50, /20, …) es deuda: o se
          // promociona a uno de los dos canónicos, o se documenta
          // explícitamente por qué necesita un nivel intermedio.
          DEFAULT: "rgb(var(--ink) / <alpha-value>)",
          muted:   "rgb(var(--ink-muted) / <alpha-value>)",
          faint:   "rgb(var(--ink-faint) / <alpha-value>)",
          dim:     "rgb(var(--ink-dim) / <alpha-value>)",
        },
        accent: {
          // Google Blue (NotebookLM signature). Replaces the previous
          // Contecflow blue→violet brand.
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",        // #1a73e8
          soft:    "rgb(var(--accent-soft) / <alpha-value>)",   // #1967d2 hover / pressed
          glow:    "rgb(var(--accent-glow) / <alpha-value>)",   // #4285f4 highlights, links
          // `accent-2` used to be the violet endpoint of the brand gradient.
          // Now an alias for `accent` so historical callsites still compile
          // but no longer render as a 2-tone gradient.
          "2":     "rgb(var(--accent) / <alpha-value>)",
        },
        success: {
          DEFAULT: "rgb(var(--success) / <alpha-value>)",       // Google green
          soft:    "rgb(var(--success-soft) / <alpha-value>)",
        },
        warning: {
          DEFAULT: "rgb(var(--warning) / <alpha-value>)",       // Google yellow
          soft:    "rgb(var(--warning-soft) / <alpha-value>)",
        },
        danger: {
          DEFAULT: "rgb(var(--danger) / <alpha-value>)",        // Google red
          soft:    "rgb(var(--danger-soft) / <alpha-value>)",
        },
        // ── Categóricos de visualización (auditoría #36, expuestos en #17) ──
        //
        // Las variables `--viz-violet` / `--viz-neutral` existían desde el #36
        // para los 6 tipos de relación del grafo doc→doc, pero SOLO como
        // variables CSS: no había utilidad de Tailwind, así que un componente
        // que necesitaba un violeta escribía `bg-purple-500/15` — un valor
        // crudo de la paleta, que no sigue el tema. Exponerlas cierra ese
        // desvío en el origen.
        viz: {
          violet:  "rgb(var(--viz-violet) / <alpha-value>)",
          neutral: "rgb(var(--viz-neutral) / <alpha-value>)",
        },
      },
      // ── `text-*` NO usa los mismos valores que `bg-*` ──────────────────────
      //
      // Auditoría 2026-09-02 (#26). `theme.textColor` es un scale propio en
      // Tailwind: si no se define, cae a `colors`, y si se define, manda para
      // las utilidades `text-*` y solo para ellas. Eso permite que un mismo
      // nombre semántico —`accent`, `warning`— resuelva a un color distinto
      // según el papel que juegue, que es exactamente lo que pide WCAG 2:
      //
      //   text-warning  → `--warning-text` (#8b5f00) — 4.67:1 sobre superficie
      //   bg-warning    → `--warning`      (#f9ab00) — relleno, lleva tinta encima
      //
      // El razonamiento completo está en `src/index.css`, junto a los tokens.
      //
      // Cada familia se declara ENTERA, incluidas las claves que no cambian de
      // valor: `extend` fusiona por clave de primer nivel y no está garantizado
      // que haga merge profundo de los objetos de color, así que listar solo
      // `ink.faint` podría borrar `ink.DEFAULT`, `ink.muted` e `ink.dim` — y el
      // síntoma sería `text-ink` sin resolver, o sea texto negro por defecto en
      // tema oscuro. Explícito e inmune a la semántica del merge.
      //
      // Las superficies (`paper*`) no aparecen porque como texto van ENCIMA de
      // un relleno, no contra una superficie: su contraste es responsabilidad
      // del relleno, y de eso responden los tokens base.
      textColor: {
        ink: {
          DEFAULT: "rgb(var(--ink) / <alpha-value>)",
          muted:   "rgb(var(--ink-muted) / <alpha-value>)",
          faint:   "rgb(var(--ink-faint-text) / <alpha-value>)",
          dim:     "rgb(var(--ink-dim) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--accent-text) / <alpha-value>)",
          soft:    "rgb(var(--accent-soft-text) / <alpha-value>)",
          glow:    "rgb(var(--accent-glow-text) / <alpha-value>)",
          "2":     "rgb(var(--accent-text) / <alpha-value>)",
        },
        success: {
          DEFAULT: "rgb(var(--success-text) / <alpha-value>)",
          soft:    "rgb(var(--success-soft-text) / <alpha-value>)",
        },
        warning: {
          DEFAULT: "rgb(var(--warning-text) / <alpha-value>)",
          soft:    "rgb(var(--warning-soft-text) / <alpha-value>)",
        },
        danger: {
          DEFAULT: "rgb(var(--danger-text) / <alpha-value>)",
          soft:    "rgb(var(--danger-soft-text) / <alpha-value>)",
        },
      },
      // ── El mismo color, distinto según sea RELLENO o TEXTO ──────────────
      //
      // `theme.textColor` es una escala propia de Tailwind: si no se define,
      // cae a `colors`; si se define, manda para las utilidades `text-*` y solo
      // para ellas. Eso permite que un nombre semántico resuelva a un color
      // distinto según el papel que juegue, que es lo que pide WCAG 2:
      //
      //   text-warning  → `--warning-text` (#8b5f00) — 4.67:1 sobre superficie
      //   bg-warning    → `--warning`      (#f9ab00) — relleno, lleva tinta encima
      //
      // Los tokens `*-text` YA estaban en `index.css`, copiados de contecmind
      // con su razonamiento entero. Lo que faltaba era esto: cablearlos. Sin
      // ello, `text-warning` pintaba el amarillo de relleno —1,93:1 sobre
      // blanco, ilegible— y el aviso de campos retenidos no se leía.
      //
      // Cada familia se declara ENTERA, incluidas las claves que no cambian:
      // `extend` fusiona por clave de primer nivel y no garantiza fusión
      // profunda de los objetos de color, así que listar solo `ink.faint`
      // podría borrar `ink.DEFAULT` y dejar el texto negro en tema oscuro.
      textColor: {
        ink: {
          DEFAULT: "rgb(var(--ink) / <alpha-value>)",
          muted: "rgb(var(--ink-muted) / <alpha-value>)",
          faint: "rgb(var(--ink-faint-text) / <alpha-value>)",
          dim: "rgb(var(--ink-dim) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--accent-text) / <alpha-value>)",
          soft: "rgb(var(--accent-soft-text) / <alpha-value>)",
          glow: "rgb(var(--accent-glow-text) / <alpha-value>)",
        },
        success: {
          DEFAULT: "rgb(var(--success-text) / <alpha-value>)",
          soft: "rgb(var(--success-soft-text) / <alpha-value>)",
        },
        warning: {
          DEFAULT: "rgb(var(--warning-text) / <alpha-value>)",
          soft: "rgb(var(--warning-soft-text) / <alpha-value>)",
        },
        danger: {
          DEFAULT: "rgb(var(--danger-text) / <alpha-value>)",
          soft: "rgb(var(--danger-soft-text) / <alpha-value>)",
        },
      },
      fontFamily: {
        // NotebookLM uses Google Sans / Roboto. We stick with Geist as the
        // workhorse (closest visual match available without licensing
        // Google Sans) and Roboto Mono for code labels.
        sans: ['"Google Sans Text"', '"Google Sans"', '"Geist"', "Roboto", "Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ['"Roboto Mono"', '"JetBrains Mono"', "ui-monospace", "monospace"],
      },
      borderRadius: {
        // Material 3 / NotebookLM use larger pill-y radii. Tokens shifted
        // up so existing `rounded-lg` cards still look right but feel
        // softer at large sizes.
        DEFAULT: "0.5rem",         // 8px
        sm: "0.375rem",            // 6px
        md: "0.5rem",              // 8px
        lg: "0.75rem",             // 12px
        xl: "1rem",                // 16px
        "2xl": "1.5rem",           // 24px — Material extra-large
        "3xl": "1.75rem",          // 28px — NotebookLM source cards
      },
      animation: {
        "pulse-slow": "pulse 2.5s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.3s ease-out",
        "slide-up": "slideUp 0.3s ease-out",
        "slide-in-right": "slideInRight 0.25s ease-out",
        "highlight-flash": "highlightFlash 2.5s ease-out forwards",
        "ambient-glow": "ambientGlow 8s ease-in-out infinite",
        // Login hero atmospherics.
        "float-orb-1": "floatOrb1 18s ease-in-out infinite",
        "float-orb-2": "floatOrb2 22s ease-in-out infinite",
        "float-orb-3": "floatOrb3 26s ease-in-out infinite",
        "gradient-shift": "gradientShift 12s ease-in-out infinite",
        "rise-stagger-1": "riseStagger 0.7s cubic-bezier(0.16,1,0.3,1) 0.05s both",
        "rise-stagger-2": "riseStagger 0.7s cubic-bezier(0.16,1,0.3,1) 0.15s both",
        "rise-stagger-3": "riseStagger 0.7s cubic-bezier(0.16,1,0.3,1) 0.25s both",
        "rise-stagger-4": "riseStagger 0.7s cubic-bezier(0.16,1,0.3,1) 0.35s both",
        "rise-stagger-5": "riseStagger 0.7s cubic-bezier(0.16,1,0.3,1) 0.45s both",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(16px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        slideInRight: {
          "0%": { transform: "translateX(100%)" },
          "100%": { transform: "translateX(0)" },
        },
        highlightFlash: {
          "0%":   { backgroundColor: "rgba(26, 115, 232, 0.30)" },
          "30%":  { backgroundColor: "rgba(26, 115, 232, 0.30)" },
          "100%": { backgroundColor: "rgba(26, 115, 232, 0.10)" },
        },
        ambientGlow: {
          "0%, 100%": { opacity: "0.4", transform: "scale(1)" },
          "50%":      { opacity: "0.7", transform: "scale(1.05)" },
        },
        // Big blurred orbs drift slowly behind the hero — never enough
        // travel that the eye locks on them, just enough to keep the
        // backdrop alive while you read.
        floatOrb1: {
          "0%, 100%": { transform: "translate3d(0, 0, 0) scale(1)" },
          "50%":      { transform: "translate3d(40px, -30px, 0) scale(1.08)" },
        },
        floatOrb2: {
          "0%, 100%": { transform: "translate3d(0, 0, 0) scale(1)" },
          "50%":      { transform: "translate3d(-50px, 40px, 0) scale(1.12)" },
        },
        floatOrb3: {
          "0%, 100%": { transform: "translate3d(0, 0, 0) scale(0.95)" },
          "50%":      { transform: "translate3d(30px, 30px, 0) scale(1.05)" },
        },
        gradientShift: {
          "0%, 100%": { backgroundPosition: "0% 50%" },
          "50%":      { backgroundPosition: "100% 50%" },
        },
        riseStagger: {
          "0%":   { opacity: "0", transform: "translateY(12px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      boxShadow: {
        // Material 3 elevation system (1dp → 5dp). We keep the legacy
        // `elevated`/`popover`/`cta` names as aliases of the matching
        // elevation level so older classNames keep rendering correctly.
        "elevation-1": "0 1px 2px 0 rgba(60,64,67,0.08), 0 1px 3px 1px rgba(60,64,67,0.06)",
        "elevation-2": "0 1px 2px 0 rgba(60,64,67,0.10), 0 2px 6px 2px rgba(60,64,67,0.08)",
        "elevation-3": "0 4px 8px 3px rgba(60,64,67,0.10), 0 1px 3px 0 rgba(60,64,67,0.12)",
        "elevation-4": "0 6px 10px 4px rgba(60,64,67,0.12), 0 2px 3px 0 rgba(60,64,67,0.14)",
        "elevation-5": "0 8px 12px 6px rgba(60,64,67,0.14), 0 4px 4px 0 rgba(60,64,67,0.16)",
        "elevated":    "0 1px 2px 0 rgba(60,64,67,0.10), 0 2px 6px 2px rgba(60,64,67,0.08)",
        "popover":     "0 4px 8px 3px rgba(60,64,67,0.10), 0 1px 3px 0 rgba(60,64,67,0.12)",
        "accent-glow": "0 0 0 1px rgba(26,115,232,0.55), 0 0 0 4px rgba(26,115,232,0.12)",
        "cta":         "0 1px 2px 0 rgba(60,64,67,0.10), 0 2px 6px 2px rgba(60,64,67,0.08)",
      },
      backgroundImage: {
        // Single-tone Google blue. Kept as a gradient utility name so
        // legacy `bg-gradient-cta` callsites keep compiling, but visually
        // it's now a flat Material button — no more blue→violet gradient.
        "gradient-cta":       "linear-gradient(180deg, rgb(var(--accent)) 0%, rgb(var(--accent-soft)) 100%)",
        "gradient-cta-hover": "linear-gradient(180deg, rgb(var(--accent-soft)) 0%, rgb(var(--accent-soft)) 100%)",
      },
      // Auditoría M30 (2026-05-26): antes había 234+ instancias de
      // `text-[0.65rem]`, `text-[11px]`, `text-[0.7rem]`, `text-[10px]`
      // dispersos. La escala canónica son 3 tokens semánticos
      // pequeños que cubren todos los micro-textos del UI:
      //   `text-3xs` (0.625rem / 10px) — meta absoluta (badges, time,
      //              keyboard hints). Solo cuando text-2xs es demasiado
      //              grande.
      //   `text-2xs` (0.6875rem / 11px) — captions, secondary labels.
      //   `text-xs`  (0.75rem / 12px) — el default de Tailwind.
      // Cualquier `text-[Npx]` queda como deuda — incremental.
      fontSize: {
        "3xs": ["0.625rem", { lineHeight: "0.875rem" }],
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      // Auditoría M31 (2026-05-26): antes había `z-[50]`, `z-[70]`,
      // `z-[72]`, `z-[75]`, `z-[80]`, `z-[90]`, `z-[110]`, `z-[200]`
      // ad-hoc en 14+ componentes, sin sistema. Cualquier modal nuevo
      // tenía que adivinar a qué nivel iba para no quedar debajo de
      // otro. Esta tabla ordenada centraliza la convención:
      //   `z-modal-bg`   — fondo de modal estándar (50)
      //   `z-modal`      — contenido de modal estándar (60)
      //   `z-popover`    — popovers, drawers anidados (70)
      //   `z-overlay`    — overlays de fullscreen panel (80)
      //   `z-command`    — command palette (90)
      //   `z-toast`      — toasts, SIEMPRE sobre todo (110)
      //   `z-focus-ring` — skip-link focus-visible (200)
      // Los `z-[NN]` arbitrarios siguen funcionando — la migración es
      // incremental; cada componente que se toque debería pasarse a
      // estos tokens.
      zIndex: {
        "modal-bg": "50",
        "modal":    "60",
        "popover":  "70",
        "overlay":  "80",
        "command":  "90",
        "toast":    "110",
        "focus-ring": "200",
      },
    },
  },
  plugins: [],
};
