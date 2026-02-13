import React, { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

// Initialize mermaid with a dark theme to match our UI
mermaid.initialize({
  startOnLoad: false,
  theme: "dark",
  themeVariables: {
    primaryColor: "#3b82f6",
    primaryTextColor: "#e4e4e7",
    primaryBorderColor: "#3f3f46",
    lineColor: "#71717a",
    secondaryColor: "#27272a",
    tertiaryColor: "#18181b",
    fontFamily: "Inter, system-ui, sans-serif",
    fontSize: "14px",
  },
  flowchart: {
    htmlLabels: true,
    curve: "basis",
  },
  securityLevel: "loose",
});

let mermaidIdCounter = 0;

interface MermaidBlockProps {
  chart: string;
}

/**
 * Renders a Mermaid diagram from a mermaid code string.
 * Renders as SVG inline; falls back to raw text on error.
 */
export function MermaidBlock({ chart }: MermaidBlockProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!chart.trim()) return;

    const id = `mermaid-${++mermaidIdCounter}`;

    const renderChart = async () => {
      try {
        const { svg: rendered } = await mermaid.render(id, chart.trim());
        setSvg(rendered);
        setError(null);
      } catch (err) {
        console.error("[MermaidBlock] Render failed:", err);
        setError(err instanceof Error ? err.message : "Failed to render diagram");
        setSvg(null);

        // Clean up any leftover element mermaid may have injected
        const orphan = document.getElementById(`d${id}`);
        if (orphan) orphan.remove();
      }
    };

    renderChart();
  }, [chart]);

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-4 my-4">
        <div className="text-xs text-red-400 mb-2 font-medium">
          ⚠ Diagram render error
        </div>
        <pre className="text-xs text-zinc-400 whitespace-pre-wrap overflow-auto">
          {chart}
        </pre>
      </div>
    );
  }

  if (!svg) {
    return (
      <div className="rounded-lg border border-zinc-700 bg-zinc-900 p-6 my-4 flex items-center justify-center">
        <div className="text-zinc-500 text-sm animate-pulse">
          Rendering diagram…
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="rounded-lg border border-zinc-700 bg-zinc-900/50 p-4 my-4 overflow-x-auto [&_svg]:mx-auto [&_svg]:max-w-full"
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
