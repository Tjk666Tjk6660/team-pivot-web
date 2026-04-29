import { useEffect, useRef, useState } from "react";
import type { Reader } from "@/api";
import { cn } from "@/lib/utils";
import { relativeTime, formatFullDateTime } from "@/lib/time";

export function ReadersPopover({
  readers,
  trigger,
}: {
  readers: Reader[];
  trigger: (open: boolean) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 text-[11px] text-[var(--text-mute)] hover:text-[var(--accent)]"
      >
        {trigger(open)}
      </button>
      {open && readers.length > 0 && (
        <div
          className={cn(
            "absolute bottom-full left-0 z-40 mb-2 max-h-[60vh] w-[18rem] overflow-y-auto rounded-[var(--r-md)] border border-[var(--line)] bg-[var(--surface)] p-2 shadow-[var(--shadow-lg)]",
          )}
        >
          <p className="mb-1.5 px-2 pt-1 text-[10.5px] font-bold uppercase tracking-wider text-[var(--text-mute)]">
            已读 · {readers.length}
          </p>
          <ul className="space-y-1">
            {readers.map((r) => (
              <li
                key={r.open_id}
                className="flex items-center gap-2 rounded-[var(--r-sm)] px-2 py-1 hover:bg-[var(--surface-alt)]"
              >
                {r.avatar_url ? (
                  <img
                    src={r.avatar_url}
                    alt=""
                    className="h-6 w-6 shrink-0 rounded-full"
                  />
                ) : (
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--surface-alt)] text-[10px] font-semibold text-[var(--text-soft)] ring-1 ring-[var(--line)]">
                    {(r.name || "?").trim().charAt(0)}
                  </span>
                )}
                <span className="min-w-0 flex-1 truncate text-[12.5px] text-[var(--text)]">
                  {r.name || r.open_id}
                </span>
                <span
                  className="shrink-0 text-[10.5px] text-[var(--text-fade)]"
                  title={formatFullDateTime(r.first_read_at)}
                >
                  {relativeTime(r.first_read_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
