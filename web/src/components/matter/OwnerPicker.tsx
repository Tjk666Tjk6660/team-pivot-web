import { useEffect, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";
import { searchContacts, type Contact } from "@/api";
import { cn } from "@/lib/utils";

// owner 存 contact.en_name（即 pinyin 约定）。
// session 用户自身作为默认值：value = session.pinyin, displayName = session.name。

export function OwnerPicker({
  value,
  onChange,
  sessionPinyin,
  sessionName,
  displayName,
  placeholder = "选择执行人",
}: {
  value: string;
  onChange: (pinyin: string, displayName: string) => void;
  sessionPinyin: string;
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
    if (value === sessionPinyin) return `${sessionName}（= 你）`;
    if (displayName) return `${displayName}（${value}）`;
    return value;
  })();

  const pickSelf = () => {
    onChange(sessionPinyin, sessionName);
    setOpen(false);
  };

  const pickContact = (c: Contact) => {
    if (!c.en_name) return;
    onChange(c.en_name, c.name);
    setOpen(false);
    setQuery("");
  };

  return (
    <div className="relative" ref={containerRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex h-11 w-full items-center justify-between rounded-md border border-slate-300 bg-white px-3 text-sm hover:bg-slate-50"
      >
        <span className={cn(value ? "text-slate-800" : "text-slate-400")}>
          {label}
        </span>
        <ChevronDown className="h-4 w-4 text-slate-400" />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-full z-30 mt-1 rounded-md border border-slate-200 bg-white shadow-md">
          <div className="flex items-center gap-1 border-b border-slate-100 p-2">
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索名字 / 拼音…"
              className="h-8 flex-1 rounded border border-slate-200 bg-slate-50 px-2 text-xs outline-none focus:border-blue-400"
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery("")}
                className="rounded p-1 hover:bg-slate-100"
                title="清空"
              >
                <X className="h-3.5 w-3.5 text-slate-500" />
              </button>
            )}
          </div>

          <div className="max-h-56 overflow-y-auto py-1">
            {/* 快捷：选自己 */}
            <button
              type="button"
              onClick={pickSelf}
              className={cn(
                "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-slate-100",
                value === sessionPinyin && "bg-blue-50",
              )}
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-blue-100 text-[10px] font-semibold text-blue-700">
                你
              </span>
              <span className="text-slate-800">{sessionName}</span>
              <span className="text-xs text-slate-500">（{sessionPinyin}）</span>
              {value === sessionPinyin && (
                <span className="ml-auto text-xs text-blue-600">✓</span>
              )}
            </button>

            <div className="my-1 border-t border-slate-100" />

            {loading && (
              <div className="px-3 py-2 text-xs text-slate-400">搜索中…</div>
            )}
            {!loading && results.length === 0 && (
              <div className="px-3 py-2 text-xs text-slate-400">
                {query ? "没有匹配项" : "输入关键词搜索联系人"}
              </div>
            )}
            {!loading &&
              results.map((c) => {
                const disabled = !c.en_name;
                const selected = !!c.en_name && value === c.en_name;
                return (
                  <button
                    key={c.open_id}
                    type="button"
                    disabled={disabled}
                    onClick={() => pickContact(c)}
                    title={disabled ? "该联系人缺少拼音（en_name），无法作为 owner" : undefined}
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm",
                      disabled
                        ? "cursor-not-allowed text-slate-400"
                        : "hover:bg-slate-100",
                      selected && !disabled && "bg-blue-50",
                    )}
                  >
                    {c.avatar_url ? (
                      <img src={c.avatar_url} alt="" className="h-5 w-5 rounded-full" />
                    ) : (
                      <span className="h-5 w-5 rounded-full bg-slate-200" />
                    )}
                    <span className={disabled ? "text-slate-400" : "text-slate-800"}>
                      {c.name}
                    </span>
                    {c.en_name ? (
                      <span className="text-xs text-slate-500">（{c.en_name}）</span>
                    ) : (
                      <span className="text-xs text-amber-600">缺 en_name</span>
                    )}
                    {selected && (
                      <span className="ml-auto text-xs text-blue-600">✓</span>
                    )}
                  </button>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}
