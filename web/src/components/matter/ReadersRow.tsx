import { Eye } from "lucide-react";
import type { Reader } from "@/api";
import { ReadersPopover } from "./ReadersPopover";

const PREVIEW_NAMES = 3;

export function ReadersRow({ readers }: { readers: Reader[] }) {
  if (readers.length === 0) return null;

  const previewNames = readers
    .slice(0, PREVIEW_NAMES)
    .map((r) => (r.name || r.open_id).trim())
    .filter(Boolean)
    .join("、");
  const more = readers.length - PREVIEW_NAMES;

  return (
    <div className="mt-2 border-t border-[var(--line-soft)] pt-2">
      <ReadersPopover
        readers={readers}
        trigger={() => (
          <>
            <Eye className="h-3 w-3 shrink-0 text-[var(--text-fade)]" />
            <span>{readers.length} 人已读</span>
            {previewNames && (
              <span className="text-[var(--text-fade)]">· {previewNames}</span>
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
