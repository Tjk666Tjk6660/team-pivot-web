import { useEffect, useRef, useState } from "react";

type MermaidModule = typeof import("mermaid");

let mermaidLoader: Promise<MermaidModule["default"]> | null = null;
let counter = 0;

function loadMermaid() {
  if (!mermaidLoader) {
    mermaidLoader = import("mermaid").then((m) => {
      m.default.initialize({
        startOnLoad: false,
        securityLevel: "strict",
        theme: "default",
        flowchart: { useMaxWidth: true },
        sequence: { useMaxWidth: true },
      });
      return m.default;
    });
  }
  return mermaidLoader;
}

export function MermaidBlock({ code }: { code: string }) {
  const idRef = useRef(`mmd_${++counter}`);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = await loadMermaid();
        const out = await mermaid.render(idRef.current, code);
        if (!cancelled) {
          setSvg(out.svg);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setSvg(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (error) {
    return (
      <div className="my-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
        <div className="mb-1 font-semibold">Mermaid 渲染失败</div>
        <div className="mb-1 text-[11px] text-amber-700">{error}</div>
        <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-amber-900">
          {code}
        </pre>
      </div>
    );
  }

  if (!svg) {
    return (
      <pre className="my-2 overflow-x-auto rounded-md border border-slate-200 bg-slate-50 p-2 font-mono text-[11px] text-slate-500">
        {code}
      </pre>
    );
  }

  return (
    <div
      className="my-2 flex justify-center overflow-x-auto rounded-md border border-slate-200 bg-white p-3"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
