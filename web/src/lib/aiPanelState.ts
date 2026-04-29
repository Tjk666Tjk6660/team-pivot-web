export function shouldShowBackgroundAIControl({
  activeThreadKey,
  currentThreadKey,
  aiOpen,
}: {
  activeThreadKey: string | null | undefined;
  currentThreadKey: string;
  aiOpen: boolean;
}): boolean {
  return !aiOpen && activeThreadKey === currentThreadKey;
}

export function shouldNotifyBackgroundAIOnClose({
  activeThreadKey,
  currentThreadKey,
}: {
  activeThreadKey: string | null | undefined;
  currentThreadKey: string;
}): boolean {
  return activeThreadKey === currentThreadKey;
}

export function shouldNotifyBackgroundAIComplete({
  backgroundThreadKey,
  activeThreadKey,
  currentThreadKey,
  aiOpen,
}: {
  backgroundThreadKey: string | null;
  activeThreadKey: string | null | undefined;
  currentThreadKey: string;
  aiOpen: boolean;
}): boolean {
  return (
    !aiOpen &&
    backgroundThreadKey === currentThreadKey &&
    activeThreadKey !== currentThreadKey
  );
}

const SCROLL_BOTTOM_THRESHOLD = 24;

export function isNearScrollBottom({
  scrollTop,
  clientHeight,
  scrollHeight,
}: {
  scrollTop: number;
  clientHeight: number;
  scrollHeight: number;
}): boolean {
  return scrollHeight - scrollTop - clientHeight <= SCROLL_BOTTOM_THRESHOLD;
}
