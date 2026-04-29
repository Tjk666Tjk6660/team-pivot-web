import { useLayoutEffect, useRef, useState } from "react";
import { isTimelineFileItem, type TimelineItem } from "@/api";
import { cn } from "@/lib/utils";
import { relativeTime } from "@/lib/time";
import { TYPE_VISUAL, shortFile } from "./timeline-config";

// 自适应 · 软圆弧蛇形折返时间轴
// - 节点数按容器宽度自适应分行
// - 每行末尾用半圆弧（arcR = ROW_V / 2）平滑连接到下一行
// - 每行起点标注方向箭头（→ / ←）
// - 每个节点下方只显示相对时间（多久前）；完整信息在 hover 的 title 提示里

const PAD_X = 64;
const PAD_Y = 14;
const H_SPACING_TARGET = 120; // 每节点理想水平间距（要容纳 status chip "planning → executing"）
const ROW_V = 96;             // 行基线垂直间距（要容纳 type + 时间 + chip 三行标签）
const ARC_R = ROW_V / 2;
const DOT_SIZE = 24;
const LABEL_H = 86;           // type + time + chip 合计高度
const MIN_PER_ROW = 2;
const LINE_COLOR = "#cbd5e1";
const MOBILE_PER_ROW_BREAKPOINT = 560;
const MOBILE_PER_ROW = 3;

type Position = {
  x: number;
  y: number;
  row: number;
  col: number;
  ltr: boolean;
};

type Layout = {
  positions: Position[];
  perRow: number;
  rows: number;
  height: number;
  arcR: number;
};

type ConnectorArrow = {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
};

function computeLayout(count: number, width: number): Layout {
  const inner = Math.max(width - PAD_X * 2, 0);
  // 根据容器宽度决定每行放几个节点
  let perRow =
    width < MOBILE_PER_ROW_BREAKPOINT
      ? MOBILE_PER_ROW
      : Math.max(Math.floor(inner / H_SPACING_TARGET) + 1, MIN_PER_ROW);
  perRow = Math.min(perRow, Math.max(count, MIN_PER_ROW));
  const hSpacing = perRow > 1 ? inner / (perRow - 1) : 0;
  const rows = Math.max(Math.ceil(count / perRow), 1);

  const positions: Position[] = Array.from({ length: count }).map((_, i) => {
    const row = Math.floor(i / perRow);
    const col = i % perRow;
    const ltr = row % 2 === 0;
    const x = PAD_X + (ltr ? col * hSpacing : (perRow - 1 - col) * hSpacing);
    const y = PAD_Y + row * ROW_V;
    return { x, y, row, col, ltr };
  });

  const height = PAD_Y + (rows - 1) * ROW_V + DOT_SIZE + LABEL_H + 4;
  return { positions, perRow, rows, height, arcR: ARC_R };
}

function buildPath(positions: Position[], arcR: number): string {
  if (positions.length === 0) return "";
  const first = positions[0];
  let d = `M ${first.x} ${first.y}`;
  for (let i = 1; i < positions.length; i++) {
    const prev = positions[i - 1];
    const curr = positions[i];
    if (prev.row === curr.row) {
      d += ` L ${curr.x} ${curr.y}`;
    } else {
      const sweep = prev.ltr ? 1 : 0;
      d += ` A ${arcR} ${arcR} 0 0 ${sweep} ${curr.x} ${curr.y}`;
    }
  }
  return d;
}

function buildConnectorArrows(
  positions: Position[],
  arcR: number,
): ConnectorArrow[] {
  const arrows: ConnectorArrow[] = [];
  const arrowLen = 18;

  for (let i = 1; i < positions.length; i++) {
    const prev = positions[i - 1];
    const curr = positions[i];
    if (prev.row === curr.row) {
      const dir = curr.x >= prev.x ? 1 : -1;
      const cx = (prev.x + curr.x) / 2;
      arrows.push({
        x1: cx - (dir * arrowLen) / 2,
        y1: curr.y,
        x2: cx + (dir * arrowLen) / 2,
        y2: curr.y,
      });
    } else {
      const x = prev.x + (prev.ltr ? arcR : -arcR);
      const y = (prev.y + curr.y) / 2;
      const ux = 0;
      const uy = 1;
      arrows.push({
        x1: x - (ux * arrowLen) / 2,
        y1: y - (uy * arrowLen) / 2,
        x2: x + (ux * arrowLen) / 2,
        y2: y + (uy * arrowLen) / 2,
      });
    }
  }

  return arrows;
}

function arrowHeadPoints(arrow: ConnectorArrow): string {
  const size = 11;
  const dx = arrow.x2 - arrow.x1;
  const dy = arrow.y2 - arrow.y1;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const px = -uy;
  const py = ux;
  const tipX = arrow.x2;
  const tipY = arrow.y2;
  const baseX = tipX - ux * size;
  const baseY = tipY - uy * size;
  const half = size * 0.48;

  return [
    `${tipX},${tipY}`,
    `${baseX + px * half},${baseY + py * half}`,
    `${baseX - px * half},${baseY - py * half}`,
  ].join(" ");
}

export function TimelineStrip({
  items,
  highlight,
  onJump,
}: {
  items: TimelineItem[];
  highlight: string | null;
  onJump: (file: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const update = () => setWidth(el.clientWidth);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  if (items.length === 0) {
    return <div className="text-xs text-[var(--text-fade)]">（空）</div>;
  }

  const layout = width > 0 ? computeLayout(items.length, width) : null;
  const d = layout ? buildPath(layout.positions, layout.arcR) : "";
  const connectorArrows = layout
    ? buildConnectorArrows(layout.positions, layout.arcR)
    : [];

  return (
    <div
      ref={containerRef}
      className="relative w-full"
      style={{ height: layout?.height ?? 60 }}
    >
      {layout && (
        <>
          {/* 路径线条 */}
          <svg
            className="pointer-events-none absolute inset-0"
            width="100%"
            height={layout.height}
            aria-hidden
          >
            <path
              d={d}
              fill="none"
              stroke={LINE_COLOR}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            {connectorArrows.map((arrow, i) => (
              <polygon
                key={`connector-arrow-${i}`}
                points={arrowHeadPoints(arrow)}
                fill={LINE_COLOR}
              />
            ))}
          </svg>

          {/* 每行起点方向箭头 */}
          {Array.from({ length: layout.rows }).map((_, r) => {
            const firstIdx = r * layout.perRow;
            const pos = layout.positions[firstIdx];
            if (!pos) return null;
            const isLTR = r % 2 === 0;
            const arrow = isLTR ? "→" : "←";
            const dx = isLTR ? -22 : 10;
            return (
              <div
                key={`arrow-${r}`}
                className="pointer-events-none absolute hidden text-[11px] font-medium text-[var(--text-fade)]"
                style={{
                  left: pos.x + dx,
                  top: pos.y - 8,
                }}
              >
                {arrow}
              </div>
            );
          })}

          {/* 节点 */}
          {items.map((item, i) => {
            const pos = layout.positions[i];
            if (!pos) return null;
            const itemIsFile = isTimelineFileItem(item);
            const fileItem = itemIsFile ? item : null;
            const actorLabel = itemIsFile ? item.creator : item.actor;
            const cfg = fileItem ? TYPE_VISUAL[fileItem.type] : null;
            const active = !!fileItem && highlight === fileItem.file;
            const key = fileItem ? fileItem.file : `owner-${item.created_at}-${i}`;
            return (
              <button
                key={key}
                type="button"
                disabled={!fileItem}
                onClick={() => fileItem && onJump(fileItem.file)}
                className="absolute flex flex-col items-center focus:outline-none disabled:cursor-default"
                style={{
                  left: pos.x - 56,
                  top: pos.y - DOT_SIZE / 2,
                  width: 112,
                }}
                title={
                  fileItem
                    ? `${fileItem.type} #${i + 1} · ${shortFile(fileItem.file)} · ${fileItem.summary}`
                    : `owner_change #${i + 1}`
                }
              >
                <span
                  className={cn(
                    "flex h-6 w-6 items-center justify-center border border-[var(--line)] bg-[var(--surface)] shadow-[var(--shadow-sm)] transition-transform",
                    fileItem ? "rounded-full" : "rotate-45 rounded-[3px]",
                    active && "scale-125 shadow-[var(--shadow-lg)]",
                  )}
                >
                  <span
                    className={cn(
                      "block h-3.5 w-3.5",
                      fileItem ? "rounded-full" : "rounded-[2px] bg-[var(--text-fade)]",
                      cfg?.dot,
                    )}
                  />
                </span>
                <span
                  className={cn(
                    "mt-1 text-[10px] font-semibold uppercase tracking-wide",
                    cfg?.pill ?? "text-[var(--text-mute)]",
                  )}
                >
                  {item.type} #{i + 1}
                </span>
                <span className="max-w-full truncate text-[10px] font-medium text-[var(--text-soft)]">
                  {actorLabel}
                </span>
                <span className="text-[10px] text-[var(--text-mute)]">
                  {relativeTime(item.created_at)}
                </span>
                {item.status_change && (
                  <span className="mt-0.5 inline-flex max-w-full items-center truncate rounded-full bg-[var(--status-project-bg)] px-1.5 py-0.5 text-[10px] text-[var(--status-project-fg)] ring-1 ring-[var(--accent-soft)]">
                    {item.status_change.from} → {item.status_change.to}
                  </span>
                )}
                {!item.status_change && item.type === "result" && item.outcome && (
                  <span
                    className={cn(
                      "mt-0.5 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] ring-1",
                      item.outcome === "finished"
                        ? "bg-[var(--status-concluded-bg)] text-[var(--status-concluded-fg)] ring-[var(--line)]"
                        : "bg-[var(--surface-alt)] text-[var(--text-soft)] ring-[var(--line-strong)]",
                    )}
                  >
                    {item.outcome}
                  </span>
                )}
              </button>
            );
          })}
        </>
      )}
    </div>
  );
}
