import { useLayoutEffect, useRef, useState } from "react";
import type { TimelineItem } from "@/api";
import { cn } from "@/lib/utils";
import { relativeTime } from "@/lib/time";
import { TYPE_VISUAL, shortFile } from "./timeline-config";

// 自适应 · 软圆弧蛇形折返时间轴
// - 节点数按容器宽度自适应分行
// - 每行末尾用半圆弧（arcR = ROW_V / 2）平滑连接到下一行
// - 每行起点标注方向箭头（→ / ←）
// - 每个节点下方只显示相对时间（多久前）；完整信息在 hover 的 title 提示里

const PAD_X = 28;
const PAD_Y = 14;
const H_SPACING_TARGET = 120; // 每节点理想水平间距（要容纳 status chip "planning → executing"）
const ROW_V = 96;             // 行基线垂直间距（要容纳 type + 时间 + chip 三行标签）
const ARC_R = ROW_V / 2;
const DOT_SIZE = 16;
const LABEL_H = 60;           // type + time + chip 合计高度
const MIN_PER_ROW = 2;

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

function computeLayout(count: number, width: number): Layout {
  const inner = Math.max(width - PAD_X * 2, 0);
  // 根据容器宽度决定每行放几个节点
  let perRow = Math.max(Math.floor(inner / H_SPACING_TARGET) + 1, MIN_PER_ROW);
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
      // 行转折：用半圆弧。prev.ltr=true 时弧线向右鼓（sweep=1 顺时针），否则向左鼓
      const sweep = prev.ltr ? 1 : 0;
      d += ` A ${arcR} ${arcR} 0 0 ${sweep} ${curr.x} ${curr.y}`;
    }
  }
  return d;
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
    return <div className="text-xs text-slate-400">（空）</div>;
  }

  const layout = width > 0 ? computeLayout(items.length, width) : null;
  const d = layout ? buildPath(layout.positions, layout.arcR) : "";

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
              stroke="#cbd5e1"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
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
                className="pointer-events-none absolute text-[11px] font-medium text-slate-400"
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
            const cfg = TYPE_VISUAL[item.type];
            const active = highlight === item.file;
            return (
              <button
                key={item.file}
                type="button"
                onClick={() => onJump(item.file)}
                className="absolute flex flex-col items-center focus:outline-none"
                style={{
                  left: pos.x - 56,
                  top: pos.y - DOT_SIZE / 2,
                  width: 112,
                }}
                title={`${item.type} #${i + 1} · ${shortFile(item.file)} · ${item.summary}`}
              >
                <span
                  className={cn(
                    "block h-4 w-4 rounded-full ring-2 ring-white transition-transform",
                    cfg.dot,
                    active && "scale-125 shadow-lg",
                  )}
                />
                <span
                  className={cn(
                    "mt-1 text-[10px] font-semibold uppercase tracking-wide",
                    cfg.pill,
                  )}
                >
                  {item.type} #{i + 1}
                </span>
                <span className="text-[10px] text-slate-500">
                  {relativeTime(item.created_at)}
                </span>
                {item.status_change && (
                  <span className="mt-0.5 inline-flex max-w-full items-center truncate rounded-full bg-purple-50 px-1.5 py-0.5 text-[10px] text-purple-700 ring-1 ring-purple-200">
                    {item.status_change.from} → {item.status_change.to}
                  </span>
                )}
                {!item.status_change && item.type === "result" && item.outcome && (
                  <span
                    className={cn(
                      "mt-0.5 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] ring-1",
                      item.outcome === "finished"
                        ? "bg-green-50 text-green-700 ring-green-200"
                        : "bg-slate-100 text-slate-600 ring-slate-300",
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
