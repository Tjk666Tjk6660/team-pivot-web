import { useEffect, useId, useRef, useState } from "react";

type Status = "loading" | "ok" | "error";

export function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState<string>("");
  const [status, setStatus] = useState<Status>("loading");
  const [error, setError] = useState<string>("");
  const containerRef = useRef<HTMLDivElement>(null);
  const uid = useId().replace(/:/g, "");

  useEffect(() => {
    let cancelled = false;

    (async () => {
      setStatus("loading");
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: "neutral",
          fontFamily:
            "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft Yahei', sans-serif",
        });
        const renderId = `mermaid-${uid}-${Date.now()}`;
        const parseOk = await mermaid.parse(code, { suppressErrors: true });
        if (!parseOk) throw new Error("mermaid syntax error");
        const { svg, bindFunctions } = await mermaid.render(renderId, code);
        if (cancelled) return;
        setSvg(svg);
        setStatus("ok");
        if (bindFunctions && containerRef.current) {
          bindFunctions(containerRef.current);
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [code, uid]);

  if (status === "error") {
    return (
      <div
        className="not-prose my-3 overflow-hidden rounded-[var(--r-md)]"
        style={{
          background: "var(--surface-alt)",
          border: "1px solid var(--line-strong)",
        }}
      >
        <div
          className="px-3 py-1.5 text-[11px] font-meta"
          style={{
            color: "var(--text-mute)",
            borderBottom: "1px solid var(--line-soft)",
          }}
        >
          mermaid · 渲染失败：{error}
        </div>
        <pre
          className="m-0 overflow-x-auto px-3 py-2 text-[12.5px] leading-[1.55]"
          style={{ color: "var(--text-soft)" }}
        >
          <code>{code}</code>
        </pre>
      </div>
    );
  }

  if (status === "loading") {
    return (
      <div
        className="not-prose my-3 rounded-[var(--r-md)] px-3 py-2 text-[12px] font-meta italic"
        style={{
          background: "var(--surface-alt)",
          border: "1px dashed var(--line)",
          color: "var(--text-mute)",
        }}
      >
        mermaid · 正在渲染图表…
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="not-prose my-3 overflow-x-auto rounded-[var(--r-md)] px-3 py-3"
      style={{
        background: "var(--surface-alt)",
        border: "1px solid var(--line)",
      }}
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
