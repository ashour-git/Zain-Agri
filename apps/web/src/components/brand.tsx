import { useId } from "react";

import { cn } from "@/lib/utils";

/*
 * Zain's logo, redrawn from the shop sign («مؤسسة زين للتنمية الزراعية»):
 * a green Z whose diagonal breaks like a lightning bolt, lime seed dots on
 * the letter, a row of seeds and a seed bag on the top bar, crossed farm
 * tools, leaves, «زين» on its left and "ain" on its right.
 *
 * ZainLogo is the full sign logo for roomy places (sign-in, emails).
 * BrandMark keeps only what survives at 24-40px: the Z, its dots and the leaf.
 */

const Z_PATH =
  "M95 30H175V48L146 86H156L118 132H175V150H95V132L124 94H114L152 48H107V62H95Z";

export function ZainLogo({ className, title = "زين للتنمية الزراعية" }: { className?: string; title?: string }) {
  const id = useId();
  const zFill = `${id}-z`;
  const leafFill = `${id}-leaf`;
  return (
    <svg viewBox="0 0 240 172" className={cn("h-auto w-56", className)} role="img" aria-label={title}>
      <defs>
        <linearGradient id={zFill} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#6cbf33" />
          <stop offset="1" stopColor="#17703a" />
        </linearGradient>
        <linearGradient id={leafFill} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#c3e05a" />
          <stop offset="1" stopColor="#5fae2c" />
        </linearGradient>
      </defs>

      {/* Row of seeds along the top bar, ending in a seed bag. */}
      <g>
        {["#8a6d3b", "#5d4b2f", "#a5925e", "#6f7a3a", "#3e3427", "#9b8a55", "#6b4f7d"].map(
          (fill, i) => (
            <circle key={fill} cx={102 + i * 9.5} cy={22} r={3.6} fill={fill} />
          ),
        )}
        <g transform="rotate(-8 178 16)">
          <rect x={169} y={4} width={18} height={23} rx={2} fill="#6cbf33" stroke="#1d5a2c" strokeWidth={1.5} />
          <circle cx={178} cy={16} r={5} fill="#fff" />
          <path d="M178 19v-5m0 2c-2-2-3.5-1.5-4-1m4 1c2-2 3.5-1.5 4-1" stroke="#17703a" strokeWidth={1.3} fill="none" strokeLinecap="round" />
        </g>
      </g>

      {/* The Z, with the lightning break in its diagonal. */}
      <path d={Z_PATH} fill={`url(#${zFill})`} />
      <g fill="#c8e04f" stroke="#2f7d22" strokeWidth={0.8}>
        <circle cx={124} cy={39} r={5.5} />
        <circle cx={162} cy={39} r={5.5} />
        <circle cx={150} cy={64} r={4.5} />
        <circle cx={126} cy={110} r={4.5} />
        <circle cx={108} cy={141} r={5.5} />
        <circle cx={163} cy={141} r={5.5} />
      </g>

      {/* Crossed fork and spade under the top bar. */}
      <g stroke="#1d5a2c" strokeWidth={2.6} strokeLinecap="round" fill="none">
        <path d="M110 56l18 18" />
        <path d="M128 56l-18 18" />
        <path d="M106 53l4 3M108 51l4 3M110 49l3 4" strokeWidth={1.6} />
      </g>
      <ellipse cx={130.5} cy={53.5} rx={3.4} ry={4.6} transform="rotate(45 130.5 53.5)" fill="#1d5a2c" />

      {/* Leaves: a big one on the right of the diagonal, small ones over «زين». */}
      <path d="M163 112C160 86 176 66 206 60C209 88 192 108 163 112Z" fill={`url(#${leafFill})`} />
      <path d="M166 108C176 92 188 79 202 64" stroke="#3d8f2c" strokeWidth={1.6} fill="none" strokeLinecap="round" />
      <circle cx={186} cy={86} r={4} fill="#d9ee86" opacity={0.85} />
      <path d="M20 66C26 52 40 48 52 52C46 64 34 70 20 66Z" fill="#5fae2c" />
      <path d="M44 72C50 60 62 58 72 62C66 72 56 76 44 72Z" fill="#7cc63a" />
      <path d="M70 104C74 94 84 90 92 92C88 102 80 106 70 104Z" fill="#5fae2c" />

      {/* «زين» on the left, "ain" on the right, both standing on the bar. */}
      <text
        x={58}
        y={124}
        textAnchor="middle"
        fontFamily="'Readex Pro Variable', 'Readex Pro', 'Segoe UI', Tahoma, sans-serif"
        fontSize={44}
        fontWeight={700}
        fill="#3d8f2c"
      >
        زين
      </text>
      <text
        x={204}
        y={145}
        textAnchor="middle"
        direction="ltr"
        fontFamily="ui-monospace, Consolas, 'Courier New', monospace"
        fontSize={26}
        fill="#7cc63a"
      >
        ain
      </text>
      <rect x={14} y={146} width={81} height={4} rx={2} fill="#17703a" />
      <rect x={175} y={150} width={56} height={3} rx={1.5} fill="#1d3d22" />
    </svg>
  );
}

/** The Z, its dots and the leaf: readable from 24 to 48px. */
export function BrandMark({ className, inverted }: { className?: string; inverted?: boolean }) {
  return (
    <span className={cn("grid size-10 shrink-0 place-items-center", className)} aria-hidden="true">
      <svg viewBox="0 0 64 64" className="size-full">
        <path
          d="M10 10H50V17L35 31H41L24 47H50V54H10V47L27 33H21L36 17H16V22H10Z"
          fill={inverted ? "#ffffff" : "#17703a"}
        />
        <g fill="#c8e04f">
          <circle cx={23} cy={13.5} r={2.6} />
          <circle cx={43} cy={50.5} r={2.6} />
        </g>
        <path d="M44 15C44 6 51 1 61 1C61 10 54 15 44 15Z" fill="#9bcb2e" />
        <path d="M45.5 13.5 56 5" stroke={inverted ? "#17703a" : "#ffffff"} strokeWidth={1.3} strokeLinecap="round" />
      </svg>
    </span>
  );
}

export function BrandWordmark({ tone = "dark" }: { tone?: "dark" | "light" }) {
  return (
    <span className="flex flex-col leading-tight">
      <span className={cn("text-base font-semibold", tone === "dark" ? "text-brand-700" : "text-white")}>
        زين للتنمية الزراعية
      </span>
      <span
        className={cn("text-xs font-medium tracking-wide", tone === "dark" ? "text-ink-muted" : "text-brand-100")}
        dir="ltr"
        lang="en"
      >
        ZAIN AGRI
      </span>
    </span>
  );
}
