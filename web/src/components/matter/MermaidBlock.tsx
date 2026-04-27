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
      <div className="my-2 rounded-md border border-[color-mix(in_srgb,var(--warn-500)_24%,var(--line))] bg-[color-mix(in_srgb,var(--warn-500)_10%,var(--surface))] p-2 text-xs text-[var(--warn-600)]">
        <div className="mb-1 font-semibold">Mermaid 渲染失败</div>
        <div className="mb-1 text-[11px] text-[var(--warn-600)]">{error}</div>
        <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-[var(--warn-600)]">
          {code}
        </pre>
      </div>
    );
  }

  if (!svg) {
    return (
      <pre className="my-2 overflow-x-auto rounded-md border border-[var(--line)] bg-[var(--surface-alt)] p-2 font-mono text-[11px] text-[var(--text-mute)]">
        {code}
      </pre>
    );
  }

  return (
    <div
      className="my-2 flex justify-center overflow-x-auto rounded-md border border-[var(--line)] bg-[var(--surface)] p-3"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
