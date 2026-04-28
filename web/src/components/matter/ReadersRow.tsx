import { Eye } from "lucide-react";
import type { Reader } from "@/api";
import { ReadersPopover } from "./ReadersPopover";

const PREVIEW_NAMES = 3;

export function ReadersRow({ readers }: { readers: Reader[] }) {
  if (readers.length === 0) return null;

  const previewReaders = readers.slice(0, PREVIEW_NAMES);
  const more = readers.length - PREVIEW_NAMES;

  return (
    <div className="mt-2 border-t border-[var(--line-soft)] pt-2">
      <ReadersPopover
        readers={readers}
        trigger={() => (
          <>
            <Eye className="h-3 w-3 shrink-0 text-[var(--text-fade)]" />
            <span>{readers.length} 人已读</span>
            {previewReaders.length > 0 && (
              <span className="ml-1 inline-flex items-center gap-1.5 text-[var(--text-soft)]">
                {previewReaders.map((r) => (
                  <span
                    key={r.open_id}
                    className="inline-flex items-center gap-1"
                  >
                    {r.avatar_url ? (
                      <img
                        src={r.avatar_url}
                        alt=""
                        className="h-4 w-4 shrink-0 rounded-full object-cover"
                      />
                    ) : (
                      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-[var(--surface-alt)] text-[9px] font-semibold text-[var(--text-soft)] ring-1 ring-[var(--line)]">
                        {(r.name || "?").trim().charAt(0)}
                      </span>
                    )}
                    <span>{(r.name || r.open_id).trim()}</span>
                  </span>
                ))}
              </span>
            )}
            {more > 0 && (
              <span className="text-[var(--text-fade)]">等 +{more}</span>
            )}
          </>
        )}
      />
    </div>
  );
}
