import { Palette } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useMarkdownStyle } from "./MarkdownStyleProvider";
import {
  isMarkdownStyleId,
  type MarkdownStyleId,
  type MarkdownStyleMeta,
} from "./markdownStyles";

const STYLE_SWATCHES: Record<
  MarkdownStyleId,
  { bg: string; accent: string; code: string }
> = {
  "code-light": { bg: "#ffffff", accent: "#0969da", code: "#f6f8fa" },
  "collab-blue": { bg: "#f3f7ff", accent: "#3370ff", code: "#dbe8ff" },
  "page-brown": { bg: "#fffdf7", accent: "#9b3f1b", code: "#2e241b" },
  "solarized-light": { bg: "#fdf6e3", accent: "#cb4b16", code: "#073642" },
  "neon-dark": { bg: "#282a36", accent: "#ff79c6", code: "#191a21" },
  "nord-dark": { bg: "#2e3440", accent: "#88c0d0", code: "#242933" },
};

function ThemeSwatch({
  style,
  active = false,
}: {
  style: MarkdownStyleMeta;
  active?: boolean;
}) {
  const swatch = STYLE_SWATCHES[style.id];
  return (
    <span
      className={`relative h-9 w-11 shrink-0 overflow-hidden rounded-[7px] ring-1 ${
        active ? "ring-[var(--accent-soft)]" : "ring-[var(--line)]"
      }`}
      style={{ background: swatch.bg }}
      aria-hidden
      title={`${style.label} 色卡`}
    >
      <span
        className="absolute left-2 right-2 top-2 h-1 rounded-full"
        style={{ background: swatch.accent }}
      />
      <span
        className="absolute left-2 top-[17px] h-1 w-4 rounded-full opacity-80"
        style={{ background: swatch.accent }}
      />
      <span
        className="absolute bottom-2 left-2 right-2 h-2 rounded-[4px]"
        style={{ background: swatch.code }}
      />
    </span>
  );
}

export function MarkdownStyleSwitcher() {
  const { styles, effectiveStyle, loading, setUserStyle } = useMarkdownStyle();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const activeStyle = styles.find((style) => style.id === effectiveStyle);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  const choose = (value: string) => {
    if (!isMarkdownStyleId(value)) return;
    void setUserStyle(value as MarkdownStyleId);
    setOpen(false);
  };

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        disabled={loading}
        onClick={() => setOpen((v) => !v)}
        className="inline-flex h-8 items-center gap-1.5 rounded-full border border-[var(--line)] bg-[var(--surface-alt)] px-2.5 text-[11.5px] font-medium text-[var(--text-soft)] transition hover:border-[var(--accent-soft)] hover:bg-[var(--accent-bg)] hover:text-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-60"
        title="切换 matter 正文 Markdown 主题"
      >
        {styles.map((style) => (
          style.id === effectiveStyle ? (
            <span key={style.id} className="contents">
              <span
                className="h-3.5 w-3.5 rounded-full ring-1 ring-[var(--line-strong)]"
                style={{
                  background: `linear-gradient(135deg, ${STYLE_SWATCHES[style.id].bg} 0 38%, ${STYLE_SWATCHES[style.id].accent} 38% 68%, ${STYLE_SWATCHES[style.id].code} 68% 100%)`,
                }}
                aria-hidden
              />
              <span className="hidden sm:inline">主题</span>
              <span className="font-semibold text-[var(--text)]">
                {style.label}
              </span>
              <span className="text-[10px] text-[var(--text-mute)]">▼</span>
            </span>
          ) : null
        ))}
        {!activeStyle && (
          <>
            <Palette className="h-3.5 w-3.5 text-current" />
            <span className="font-semibold text-[var(--text)]">默认</span>
          </>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-80 overflow-hidden rounded-[var(--r-md)] border border-[var(--line-strong)] bg-[var(--surface)] p-2 shadow-[var(--shadow-lg)]">
          <div className="mb-1 flex items-center justify-between px-2 py-1">
            <span className="text-[11px] font-semibold text-[var(--text)]">
              Markdown 正文主题
            </span>
            <span className="text-[10px] text-[var(--text-mute)]">
              仅影响正文
            </span>
          </div>
          {styles.map((style) => {
            const active = style.id === effectiveStyle;
            return (
              <button
                key={style.id}
                type="button"
                onClick={() => choose(style.id)}
                className={`flex w-full items-center gap-3 rounded-[var(--r-sm)] px-2.5 py-2.5 text-left transition ${
                  active
                    ? "bg-[color-mix(in_srgb,var(--accent-bg)_62%,var(--surface))] ring-1 ring-[var(--accent-soft)]"
                    : "text-[var(--text-soft)] hover:bg-[var(--surface-alt)]"
                }`}
              >
                <ThemeSwatch style={style} active={active} />
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 text-[12.5px] font-semibold text-[var(--text)]">
                    {style.label}
                    {active && (
                      <span className="rounded-full bg-[var(--surface)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--accent)] ring-1 ring-[var(--accent-soft)]">
                        当前
                      </span>
                    )}
                  </span>
                  <span className="mt-0.5 block text-[11px] leading-4 text-[var(--text-mute)]">
                    {style.description}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
