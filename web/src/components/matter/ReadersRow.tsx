import { Eye } from "lucide-react";
import type { Reader } from "@/api";
import { ReadersPopover } from "./ReadersPopover";

// Two preview budgets driven purely by Tailwind breakpoints:
//   - Mobile (< sm = 640 px):  show 4 readers, hide the rest with `sm:hidden`-
//     gated avatars + a mobile-only "+more" tail.
//   - Desktop (>= sm):         show up to 12 readers and a desktop-only "+more"
//     tail.
// Same DOM serves both layouts — no JS resize / matchMedia listener, so SSR
// and first paint are stable. The two "+more" chips are mutually exclusive
// via `sm:hidden` / `hidden sm:inline`.
const MOBILE_PREVIEW = 4;
const DESKTOP_PREVIEW = 12;

export function ReadersRow({ readers }: { readers: Reader[] }) {
  if (readers.length === 0) return null;

  const desktopReaders = readers.slice(0, DESKTOP_PREVIEW);
  const desktopMore = readers.length - DESKTOP_PREVIEW;
  const mobileMore = readers.length - MOBILE_PREVIEW;

  return (
    <div className="mt-2 border-t border-[var(--line-soft)] pt-2">
      <ReadersPopover
        readers={readers}
        trigger={() => (
          <>
            <Eye className="h-3 w-3 shrink-0 text-[var(--text-fade)]" />
            <span>{readers.length} 人已读</span>
            <span className="ml-1 inline-flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[var(--text-soft)]">
              {desktopReaders.map((r, i) => (
                <span
                  key={r.open_id}
                  className={
                    "inline-flex items-center gap-1 " +
                    (i >= MOBILE_PREVIEW ? "hidden sm:inline-flex" : "")
                  }
                >
                  {r.avatar_url ? (
                    <img
                      src={r.avatar_url}
                      alt=""
                      className="h-4 w-4 shrink-0 rounded-full object-cover"
                      loading="lazy"
                      referrerPolicy="no-referrer"
                    />
                  ) : (
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-[var(--surface-alt)] text-[9px] font-semibold text-[var(--text-soft)] ring-1 ring-[var(--line)]">
                      {(r.name || "?").trim().charAt(0)}
                    </span>
                  )}
                  <span className="max-w-[8rem] truncate">
                    {(r.name || r.open_id).trim()}
                  </span>
                </span>
              ))}
            </span>
            {mobileMore > 0 && (
              <span className="ml-1 text-[var(--text-fade)] sm:hidden">
                等 +{mobileMore}
              </span>
            )}
            {desktopMore > 0 && (
              <span className="ml-1 hidden text-[var(--text-fade)] sm:inline">
                等 +{desktopMore}
              </span>
            )}
          </>
        )}
      />
    </div>
  );
}
