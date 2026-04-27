import { useEffect, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";
import { searchContacts, type Contact } from "@/api";
import { cn } from "@/lib/utils";

// owner 存飞书 open_id（规范唯一键）。
// 显示层由服务端 name resolver 兜底（users → contacts → 原始值，见 pivot-memo.md §5）。
// 前端这里靠 displayName 缓存最近一次挑选的展示名，避免下拉关闭后显示裸 open_id。

export function OwnerPicker({
  value,
  onChange,
  sessionOpenId,
  sessionName,
  displayName,
  placeholder = "选择执行人",
}: {
  value: string;
  onChange: (openId: string, displayName: string) => void;
  sessionOpenId: string;
  sessionName: string;
  displayName?: string;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(async () => {
      setLoading(true);
      try {
        setResults(await searchContacts(query));
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => {
      if (debounceRef.current) window.clearTimeout(debounceRef.current);
    };
  }, [query, open]);

  const label = (() => {
    if (!value) return placeholder;
    if (value === sessionOpenId) return `${sessionName}（= 你）`;
    if (displayName) return displayName;
    return value;
  })();

  const pickSelf = () => {
    onChange(sessionOpenId, sessionName);
    setOpen(false);
  };

  const pickContact = (c: Contact) => {
    onChange(c.open_id, c.name);
    setOpen(false);
    setQuery("");
  };

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex h-11 w-full items-center justify-between rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-3 text-sm hover:bg-[var(--surface-alt)]"
      >
        <span className={cn(value ? "text-[var(--text)]" : "text-[var(--text-fade)]")}>
          {label}
        </span>
        <ChevronDown className="h-4 w-4 text-[var(--text-fade)]" />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 rounded-md border border-[var(--line)] bg-[var(--surface)] shadow-[var(--shadow-md)]">
          <div className="flex items-center gap-1 border-b border-[var(--line-soft)] p-2">
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索名字 / 拼音…"
              className="h-8 flex-1 rounded border border-[var(--line)] bg-[var(--surface-alt)] px-2 text-xs outline-none focus:border-[var(--accent)]"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                className="rounded p-1 hover:bg-[var(--surface-alt)]"
                title="清空"
              >
                <X className="h-3.5 w-3.5 text-[var(--text-mute)]" />
              </button>
            )}
          </div>

          <div className="max-h-56 overflow-y-auto py-1">
            {/* 快捷：选自己 */}
            <button
              type="button"
              onClick={pickSelf}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-[var(--surface-alt)]",
                value === sessionOpenId && "bg-[var(--accent-bg)]",
              )}
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[var(--accent-bg)] text-[10px] font-semibold text-[var(--accent)]">
                你
              </span>
              <span className="text-[var(--text)]">{sessionName}</span>
              {value === sessionOpenId && (
                <span className="ml-auto text-xs text-[var(--accent)]">✓</span>
              )}
            </button>

            <div className="my-1 border-t border-[var(--line-soft)]" />

            {loading && (
              <div className="px-3 py-2 text-xs text-[var(--text-fade)]">搜索中…</div>
            )}
            {!loading && results.length === 0 && (
              <div className="px-3 py-2 text-xs text-[var(--text-fade)]">
                {query ? "没有匹配项" : "输入关键词搜索联系人"}
              </div>
            )}
            {!loading &&
              results.map((c) => {
                const selected = value === c.open_id;
                return (
                  <button
                    key={c.open_id}
                    type="button"
                    onClick={() => pickContact(c)}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-[var(--surface-alt)]",
                      selected && "bg-[var(--accent-bg)]",
                    )}
                  >
                    {c.avatar_url ? (
                      <img src={c.avatar_url} alt="" className="h-5 w-5 rounded-full" />
                    ) : (
                      <span className="h-5 w-5 rounded-full bg-[var(--line-strong)]" />
                    )}
                    <span className="text-[var(--text)]">{c.name}</span>
                    {c.en_name && (
                      <span className="text-xs text-[var(--text-mute)]">（{c.en_name}）</span>
                    )}
                    {selected && <span className="ml-auto text-xs text-[var(--accent)]">✓</span>}
                  </button>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}
