import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, FileText, Plus, Pencil } from "lucide-react";
import { toast } from "sonner";
import { fetchAIFiles, type AIThreadFiles } from "@/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

type Mode = "reply_target" | "reference";

export function FileTreeBrowser({
  mode,
  triggerLabel,
  triggerIcon = "plus",
  currentCategory,
  currentSlug,
  selected,
  excludePaths,
  onConfirm,
}: {
  mode: Mode;
  triggerLabel?: string;
  triggerIcon?: "plus" | "pencil";
  currentCategory: string;
  currentSlug: string;
  selected: string[];
  excludePaths?: string[]; // paths to filter out (e.g. the current reply target when picking references)
  onConfirm: (files: string[]) => void;
}) {
  const [open, setOpen] = useState(false);

  const Icon = triggerIcon === "pencil" ? Pencil : Plus;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={triggerLabel ?? "选择文件"}
        className="flex h-6 shrink-0 items-center justify-center gap-1 rounded border px-1.5 text-xs text-muted-foreground transition-colors hover:border-blue-300 hover:text-blue-600"
      >
        <Icon className="h-3 w-3" />
        {triggerLabel && <span>{triggerLabel}</span>}
      </button>
      <FileTreeDialog
        open={open}
        onClose={() => setOpen(false)}
        mode={mode}
        currentCategory={currentCategory}
        currentSlug={currentSlug}
        initialSelected={selected}
        excludePaths={excludePaths}
        onConfirm={(files) => {
          onConfirm(files);
          setOpen(false);
        }}
      />
    </>
  );
}

function FileTreeDialog({
  open,
  onClose,
  mode,
  currentCategory,
  currentSlug,
  initialSelected,
  excludePaths,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  mode: Mode;
  currentCategory: string;
  currentSlug: string;
  initialSelected: string[];
  excludePaths?: string[];
  onConfirm: (files: string[]) => void;
}) {
  const [items, setItems] = useState<AIThreadFiles[]>([]);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [draft, setDraft] = useState<string[]>([]);

  const isSingle = mode === "reply_target";
  const title = isSingle
    ? "选择回复对象（单选）"
    : "选择引用其他文件（多选）";

  useEffect(() => {
    if (!open) return;
    setDraft([...initialSelected]);
    setQuery("");
    setExpanded(new Set([`${currentCategory}/${currentSlug}`]));
    setLoading(true);
    fetchAIFiles()
      .then(setItems)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleExpand = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(key) ? next.delete(key) : next.add(key);
      return next;
    });
  };

  const togglePath = (path: string) => {
    setDraft((prev) => {
      if (isSingle) return prev[0] === path ? [] : [path];
      if (prev.includes(path)) return prev.filter((p) => p !== path);
      return [...prev, path];
    });
  };

  const lowerQuery = query.toLowerCase();
  const excludeSet = new Set(excludePaths ?? []);

  const filtered = items
    .map((t) => ({
      ...t,
      files: t.files.filter((f) => {
        if (excludeSet.has(f.path)) return false;
        if (!query) return true;
        return (
          f.filename.toLowerCase().includes(lowerQuery) ||
          t.title.toLowerCase().includes(lowerQuery)
        );
      }),
    }))
    .filter((t) => t.files.length > 0);

  const sorted = [
    ...filtered.filter((t) => t.category === currentCategory && t.slug === currentSlug),
    ...filtered.filter((t) => !(t.category === currentCategory && t.slug === currentSlug)),
  ];

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="flex max-h-[80vh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <div className="flex items-center gap-2 py-1">
          <Input
            placeholder="搜索文件名或讨论标题…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="h-8 text-sm"
          />
          {!isSingle && (
            <span className="shrink-0 text-xs text-muted-foreground">
              已选 {draft.length}
            </span>
          )}
        </div>

        <div className="flex-1 overflow-y-auto rounded border">
          {loading && (
            <p className="py-8 text-center text-xs text-muted-foreground">加载中…</p>
          )}
          {!loading && sorted.length === 0 && (
            <p className="py-8 text-center text-xs text-muted-foreground">无匹配文件</p>
          )}
          {sorted.map((thread) => {
            const threadKey = `${thread.category}/${thread.slug}`;
            const isCurrent = thread.category === currentCategory && thread.slug === currentSlug;
            const isExpanded = expanded.has(threadKey);

            return (
              <div key={threadKey}>
                <button
                  type="button"
                  onClick={() => toggleExpand(threadKey)}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-muted/50"
                >
                  {isExpanded ? (
                    <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                  )}
                  <span className="font-medium">{thread.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {thread.category}/{thread.slug}
                  </span>
                  {isCurrent && (
                    <span className="ml-auto rounded-full bg-blue-100 px-1.5 py-0.5 text-xs text-blue-600 dark:bg-blue-950 dark:text-blue-300">
                      当前
                    </span>
                  )}
                </button>

                {isExpanded && (
                  <div className="border-t bg-muted/20">
                    {thread.files.map((file) => {
                      const isSelected = draft.includes(file.path);
                      return (
                        <label
                          key={file.path}
                          className={`flex cursor-pointer items-center gap-3 px-6 py-1.5 text-xs transition-colors hover:bg-muted/50 ${
                            isSelected ? "bg-blue-50 dark:bg-blue-950/40" : ""
                          }`}
                        >
                          <input
                            type={isSingle ? "radio" : "checkbox"}
                            name={isSingle ? "reply-target" : undefined}
                            checked={isSelected}
                            onChange={() => togglePath(file.path)}
                            className="h-3.5 w-3.5 accent-blue-500"
                          />
                          <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                          <span className="flex-1 font-mono">{file.filename}</span>
                          {file.type && (
                            <span className="rounded bg-muted px-1.5 py-0.5 text-muted-foreground">
                              {file.type}
                            </span>
                          )}
                          {file.author && (
                            <span className="text-muted-foreground">{file.author}</span>
                          )}
                        </label>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button
            onClick={() => onConfirm(draft)}
            disabled={isSingle && draft.length === 0}
          >
            {isSingle
              ? draft.length === 0 ? "请选一个文件" : "确认"
              : `确认（${draft.length} 个）`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
