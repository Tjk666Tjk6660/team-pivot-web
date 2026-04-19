import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { searchContacts, type Contact, type MentionBlock } from "@/api";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const COMMENTS_MIN = 1;

export function MentionField({
  value,
  onChange,
  resolvedNames,
}: {
  value: MentionBlock;
  onChange: (v: MentionBlock) => void;
  resolvedNames?: Record<string, string>;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(false);
  const [focused, setFocused] = useState(false);
  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    if (debounceRef.current) window.clearTimeout(debounceRef.current);
    if (!focused) return;
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
  }, [query, focused]);

  const add = (c: Contact) => {
    if (value.open_ids.includes(c.open_id)) return;
    onChange({ ...value, open_ids: [...value.open_ids, c.open_id] });
    if (resolvedNames) resolvedNames[c.open_id] = c.name;
    setQuery("");
  };
  const remove = (oid: string) => {
    onChange({ ...value, open_ids: value.open_ids.filter((x) => x !== oid) });
  };
  const names = resolvedNames ?? {};

  return (
    <div className="rounded-md border bg-muted/30 p-3 space-y-3">
      <Label className="text-xs font-semibold">圈人（@mention）</Label>
      <div className="relative">
        <div className="flex min-h-9 flex-wrap items-center gap-1.5 rounded-md border bg-background p-1.5">
          {value.open_ids.map((oid) => (
            <span
              key={oid}
              className="inline-flex items-center gap-1 rounded bg-blue-50 px-2 py-0.5 text-xs text-blue-700"
            >
              @{names[oid] ?? oid.slice(0, 8)}
              <button
                type="button"
                onClick={() => remove(oid)}
                className="hover:text-blue-900"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => window.setTimeout(() => setFocused(false), 200)}
            placeholder={value.open_ids.length === 0 ? "搜索名字加人…" : "继续加人…"}
            className="flex-1 min-w-32 bg-transparent text-sm outline-none"
          />
        </div>
        {focused && (
          <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-56 overflow-auto rounded-md border bg-white dark:bg-zinc-900 shadow-md">
            {loading && (
              <div className="p-2.5 text-xs text-muted-foreground">搜索中…</div>
            )}
            {!loading && results.length === 0 && (
              <div className="p-2.5 text-xs text-muted-foreground">
                没有匹配项。试试顶部的"同步联系人"按钮。
              </div>
            )}
            {!loading &&
              results.map((c) => {
                const selected = value.open_ids.includes(c.open_id);
                return (
                  <button
                    key={c.open_id}
                    type="button"
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => add(c)}
                    disabled={selected}
                    className={
                      selected
                        ? "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm bg-blue-50 dark:bg-blue-950 text-blue-700 dark:text-blue-300 cursor-default"
                        : "flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-sm hover:bg-zinc-100 dark:hover:bg-zinc-800"
                    }
                  >
                    {c.avatar_url && (
                      <img src={c.avatar_url} alt="" className="h-5 w-5 rounded-full" />
                    )}
                    <span>{c.name}</span>
                    {c.en_name && (
                      <span className="text-xs text-muted-foreground">({c.en_name})</span>
                    )}
                    {selected && <span className="ml-auto text-xs">✓</span>}
                  </button>
                );
              })}
          </div>
        )}
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="mention-comments" className="text-xs">
          跟他们说一句话（必填）
        </Label>
        <Input
          id="mention-comments"
          value={value.comments}
          onChange={(e) => onChange({ ...value, comments: e.target.value })}
          maxLength={500}
          placeholder="这个方案希望你们 review"
        />
      </div>
    </div>
  );
}

export function isMentionValid(m: MentionBlock): boolean {
  if (m.open_ids.length === 0) return true;
  return m.comments.trim().length >= COMMENTS_MIN;
}

export function emptyMention(): MentionBlock {
  return { open_ids: [], comments: "" };
}
