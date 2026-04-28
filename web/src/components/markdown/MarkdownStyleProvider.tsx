import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { toast } from "sonner";
import {
  fetchMarkdownStyles,
  updateMyMarkdownStyle,
  type MarkdownStyleMeta as ApiMarkdownStyleMeta,
} from "@/api";
import {
  DEFAULT_MARKDOWN_STYLE,
  MARKDOWN_STYLES,
  isMarkdownStyleId,
  normalizeMarkdownStyle,
  type MarkdownStyleId,
  type MarkdownStyleMeta,
} from "./markdownStyles";

type MarkdownStyleContextValue = {
  styles: MarkdownStyleMeta[];
  effectiveStyle: MarkdownStyleId;
  userStyle: MarkdownStyleId | null;
  systemDefaultStyle: MarkdownStyleId | null;
  loading: boolean;
  setUserStyle: (style: MarkdownStyleId) => Promise<void>;
};

const MarkdownStyleContext = createContext<MarkdownStyleContextValue | null>(null);

function normalizeStyles(styles: ApiMarkdownStyleMeta[]): MarkdownStyleMeta[] {
  const normalized = styles
    .filter((style): style is MarkdownStyleMeta =>
      ["light", "dark"].includes(style.tone) &&
      isMarkdownStyleId(style.id),
    );
  return normalized.length > 0
    ? normalized
    : MARKDOWN_STYLES.map((style) => ({ ...style }));
}

function nullableStyle(value: unknown): MarkdownStyleId | null {
  return isMarkdownStyleId(value) ? value : null;
}

export function MarkdownStyleProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [styles, setStyles] = useState<MarkdownStyleMeta[]>(
    MARKDOWN_STYLES.map((style) => ({ ...style })),
  );
  const [effectiveStyle, setEffectiveStyle] =
    useState<MarkdownStyleId>(DEFAULT_MARKDOWN_STYLE);
  const [userStyle, setUserStyleState] = useState<MarkdownStyleId | null>(null);
  const [systemDefaultStyle, setSystemDefaultStyle] =
    useState<MarkdownStyleId | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetchMarkdownStyles()
      .then((payload) => {
        if (cancelled) return;
        setStyles(normalizeStyles(payload.styles));
        setUserStyleState(nullableStyle(payload.user_style));
        setSystemDefaultStyle(nullableStyle(payload.system_default_style));
        setEffectiveStyle(normalizeMarkdownStyle(payload.effective_style));
      })
      .catch(() => {
        if (cancelled) return;
        setEffectiveStyle(DEFAULT_MARKDOWN_STYLE);
        toast.error("Markdown 主题加载失败，已使用默认主题");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const setUserStyle = useCallback(
    async (style: MarkdownStyleId) => {
      const previousEffective = effectiveStyle;
      const previousUser = userStyle;
      setEffectiveStyle(style);
      setUserStyleState(style);
      try {
        const saved = await updateMyMarkdownStyle(style);
        setEffectiveStyle(normalizeMarkdownStyle(saved.effective_style));
        setUserStyleState(normalizeMarkdownStyle(saved.user_style));
      } catch (e) {
        setEffectiveStyle(previousEffective);
        setUserStyleState(previousUser);
        toast.error(e instanceof Error ? e.message : String(e));
      }
    },
    [effectiveStyle, userStyle],
  );

  const value = useMemo(
    () => ({
      styles,
      effectiveStyle,
      userStyle,
      systemDefaultStyle,
      loading,
      setUserStyle,
    }),
    [styles, effectiveStyle, userStyle, systemDefaultStyle, loading, setUserStyle],
  );

  return (
    <MarkdownStyleContext.Provider value={value}>
      {children}
    </MarkdownStyleContext.Provider>
  );
}

export function useMarkdownStyle() {
  const value = useContext(MarkdownStyleContext);
  if (!value) {
    throw new Error("useMarkdownStyle must be used inside MarkdownStyleProvider");
  }
  return value;
}
