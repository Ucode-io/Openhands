import React from "react";
import { cn } from "#/utils/utils";
import { MarkdownRenderer } from "#/components/features/markdown/markdown-renderer";
import type {
  SidebarStructure,
  SidebarCategory,
  SidebarItem,
} from "#/hooks/use-doc-generation";

interface ProjectDocEditorProps {
  projectId: string;
  onBack: () => void;
  initialContent?: string;
  sidebarStructure?: SidebarStructure | null;
  documentation?: Record<string, string> | null;
}

// ---- Types ----
interface DocSection {
  id: string;
  title: string;
  content: string;
  level: 1 | 2 | 3;
}

interface SidebarNode {
  id: string;
  title: string;
  level: 1 | 2 | 3;
  children?: SidebarNode[];
}

// ---- Helpers ----
function parseMarkdownSections(markdown: string): DocSection[] {
  if (!markdown || !markdown.trim()) return [];

  const sections: DocSection[] = [];
  const headerRegex = /^(#{1,3}) +(?:\d+\.\s*)?(.+)$/gm;
  const matches: { title: string; startIndex: number; level: 1 | 2 | 3 }[] = [];
  let m: RegExpExecArray | null;

  while ((m = headerRegex.exec(markdown)) !== null) {
    const lvl = Math.min(m[1].length, 3) as 1 | 2 | 3;
    matches.push({ title: m[2].trim(), startIndex: m.index, level: lvl });
  }

  if (matches.length === 0) {
    return [{ id: "documentation", title: "Documentation", content: markdown.trim(), level: 1 }];
  }

  let currentH1 = "";
  let currentH2 = "";

  for (let i = 0; i < matches.length; i++) {
    const start = matches[i].startIndex;
    const end = i + 1 < matches.length ? matches[i + 1].startIndex : markdown.length;
    const { title, level } = matches[i];

    let id: string;
    if (level === 1) {
      currentH1 = title;
      currentH2 = "";
      id = title;
    } else if (level === 2) {
      currentH2 = title;
      id = currentH1 ? `${currentH1} > ${title}` : title;
    } else {
      const prefix = currentH1
        ? currentH2 ? `${currentH1} > ${currentH2}` : currentH1
        : "";
      id = prefix ? `${prefix} > ${title}` : title;
    }

    sections.push({ id, title, content: markdown.substring(start, end).trim(), level });
  }

  return sections;
}

function buildSidebarTree(sections: DocSection[]): SidebarNode[] {
  const tree: SidebarNode[] = [];
  for (const sec of sections) {
    if (sec.level === 1) {
      tree.push({ id: sec.id, title: sec.title, level: 1, children: [] });
    } else if (sec.level === 2) {
      const parent = tree[tree.length - 1];
      if (parent) {
        parent.children = parent.children || [];
        parent.children.push({ id: sec.id, title: sec.title, level: 2, children: [] });
      } else {
        tree.push({ id: sec.id, title: sec.title, level: 2 });
      }
    } else if (sec.level === 3) {
      const parent = tree[tree.length - 1];
      if (parent?.children && parent.children.length > 0) {
        const h2Parent = parent.children[parent.children.length - 1];
        h2Parent.children = h2Parent.children || [];
        h2Parent.children.push({ id: sec.id, title: sec.title, level: 3 });
      } else {
        tree.push({ id: sec.id, title: sec.title, level: 3 });
      }
    }
  }
  return tree;
}

// ---- Main Component ----
export function ProjectDocEditor({
  projectId,
  onBack,
  initialContent,
  sidebarStructure,
  documentation,
}: ProjectDocEditorProps) {
  const [sections, setSections] = React.useState<DocSection[]>([]);
  const [activeId, setActiveId] = React.useState<string | null>(null);
  const [openGroups, setOpenGroups] = React.useState<Set<string>>(new Set());
  const [feedback, setFeedback] = React.useState<"yes" | "no" | null>(null);

  const hasSidebarMode = !!(sidebarStructure && documentation);
  const [activeSlug, setActiveSlug] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (hasSidebarMode) {
      const cats = sidebarStructure!.categories;
      if (cats.length > 0 && cats[0].items.length > 0) {
        setActiveSlug(cats[0].items[0].slug);
        const groups = new Set<string>();
        cats.forEach((c) => groups.add(c.name));
        setOpenGroups(groups);
      }
    } else if (initialContent) {
      const parsed = parseMarkdownSections(initialContent);
      setSections(parsed);
      if (parsed.length > 0) {
        const firstMeaningful = parsed.find((s) => s.content && s.content.length > 50) || parsed[0];
        setActiveId(firstMeaningful.id);
      }
      const groups = new Set<string>();
      parsed.forEach((s) => {
        if (s.level === 1 || s.level === 2) groups.add(s.id);
      });
      setOpenGroups(groups);
    }
  }, [initialContent, hasSidebarMode, sidebarStructure]);

  const sidebarTree = React.useMemo(() => buildSidebarTree(sections), [sections]);

  const activeContent = React.useMemo(() => {
    if (hasSidebarMode && activeSlug && documentation) {
      const filename = activeSlug.replace("/docs/", "") + ".md";
      return documentation[filename] || null;
    }
    if (activeId && sections.length > 0) {
      return sections.find((s) => s.id === activeId)?.content ?? null;
    }
    return null;
  }, [hasSidebarMode, activeSlug, documentation, activeId, sections]);

  const activeDisplayTitle = React.useMemo(() => {
    if (hasSidebarMode && activeSlug && sidebarStructure) {
      for (const cat of sidebarStructure.categories) {
        const item = cat.items.find((i) => i.slug === activeSlug);
        if (item) return item.title;
      }
      return null;
    }
    if (activeId) {
      const sec = sections.find((s) => s.id === activeId);
      return sec ? sec.title : activeId;
    }
    return null;
  }, [hasSidebarMode, activeSlug, sidebarStructure, activeId, sections]);

  const activeCategoryName = React.useMemo(() => {
    if (hasSidebarMode && activeSlug && sidebarStructure) {
      for (const cat of sidebarStructure.categories) {
        if (cat.items.find((i) => i.slug === activeSlug)) {
          return cat.name.replace(/_/g, " ");
        }
      }
    }
    return null;
  }, [hasSidebarMode, activeSlug, sidebarStructure]);

  const allItems = React.useMemo(() => {
    if (hasSidebarMode && sidebarStructure) {
      return sidebarStructure.categories.flatMap((c) => c.items);
    }
    return [];
  }, [hasSidebarMode, sidebarStructure]);

  const currentIndex = allItems.findIndex((i) => i.slug === activeSlug);
  const prevItem = currentIndex > 0 ? allItems[currentIndex - 1] : null;
  const nextItem = currentIndex < allItems.length - 1 ? allItems[currentIndex + 1] : null;

  const toggleGroup = (groupId: string) => {
    setOpenGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  };

  return (
    <div className="flex h-full w-full overflow-hidden bg-zinc-950">
      {/* ═══════════════════════════════════════════════════ */}
      {/* SIDEBAR – Dark Theme Docs Navigation               */}
      {/* ═══════════════════════════════════════════════════ */}
      <aside className="flex flex-col h-full overflow-hidden w-[260px] min-w-[260px] border-r border-zinc-800 bg-zinc-900">
        {/* Back link */}
        <div className="px-5 pt-4 pb-3 border-b border-zinc-800">
          <button
            type="button"
            onClick={onBack}
            className="flex items-center gap-2 text-sm text-zinc-500 hover:text-zinc-200 transition-colors"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M19 12H5M12 19l-7-7 7-7" />
            </svg>
            {/* eslint-disable-next-line i18next/no-literal-string */}
            <span>Back to Projects</span>
          </button>
        </div>

        {/* Sidebar items */}
        <div className="flex-1 overflow-y-auto py-2">
          {hasSidebarMode ? (
            /* ─── SIDEBAR-STRUCTURE MODE ─── */
            sidebarStructure!.categories.map((cat) => (
              <div key={cat.name} className="mb-1">
                {/* Category header */}
                <div className="px-5 pt-5 pb-1.5 text-[11px] font-bold tracking-widest text-zinc-500 uppercase select-none">
                  {cat.name.replace(/_/g, " ")}
                </div>

                {/* Items – NO chevron arrows */}
                {cat.items.map((item) => {
                  const isActive = activeSlug === item.slug;
                  return (
                    <button
                      type="button"
                      key={item.slug}
                      onClick={() => {
                        setActiveSlug(item.slug);
                        setFeedback(null);
                      }}
                      className={cn(
                        "w-full text-left text-[13px] py-1.5 px-5 transition-all duration-150 block truncate",
                        isActive
                          ? "text-white font-medium bg-zinc-800 border-l-2 border-blue-500"
                          : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50 border-l-2 border-transparent"
                      )}
                    >
                      {item.title}
                    </button>
                  );
                })}
              </div>
            ))
          ) : (
            /* ─── LEGACY MARKDOWN-PARSED MODE ─── */
            <>
              <div className="px-5 pt-5 pb-1.5 text-[11px] font-bold tracking-widest text-zinc-500 uppercase select-none">
                Documentation
              </div>

              {sidebarTree.length > 0 ? (
                sidebarTree.map((h1Node) => {
                  const hasChildren = h1Node.children && h1Node.children.length > 0;

                  if (!hasChildren) {
                    const isActive = activeId === h1Node.id;
                    return (
                      <button
                        type="button"
                        key={h1Node.id}
                        onClick={() => setActiveId(h1Node.id)}
                        className={cn(
                          "w-full text-left text-[13px] py-1.5 px-5 transition-all duration-150 block truncate",
                          isActive
                            ? "text-white font-medium bg-zinc-800 border-l-2 border-blue-500"
                            : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50 border-l-2 border-transparent"
                        )}
                      >
                        {h1Node.title}
                      </button>
                    );
                  }

                  const isOpen = openGroups.has(h1Node.id);
                  return (
                    <div key={h1Node.id}>
                      <button
                        type="button"
                        onClick={() => {
                          toggleGroup(h1Node.id);
                          if (h1Node.children && h1Node.children.length > 0) {
                            setActiveId(h1Node.children[0].id);
                          }
                        }}
                        className="w-full flex items-center gap-2 text-left text-[13px] py-1.5 px-5 text-zinc-300 hover:text-white hover:bg-zinc-800/50 transition-colors"
                      >
                        <svg
                          width="8"
                          height="8"
                          viewBox="0 0 8 8"
                          fill="currentColor"
                          className={cn(
                            "shrink-0 opacity-50 transition-transform duration-150",
                            isOpen ? "rotate-90" : "rotate-0"
                          )}
                        >
                          <path d="M2 1l4 3-4 3V1z" />
                        </svg>
                        <span className="truncate font-medium">{h1Node.title}</span>
                      </button>

                      {isOpen && h1Node.children!.map((h2Node) => {
                        const isChildActive = activeId === h2Node.id;
                        return (
                          <button
                            type="button"
                            key={h2Node.id}
                            onClick={() => setActiveId(h2Node.id)}
                            className={cn(
                              "w-full text-left text-[13px] py-1 pl-9 pr-5 transition-all duration-150 block truncate",
                              isChildActive
                                ? "text-white font-medium bg-zinc-800"
                                : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50"
                            )}
                          >
                            {h2Node.title}
                          </button>
                        );
                      })}
                    </div>
                  );
                })
              ) : (
                <div className="px-5 py-4 text-xs text-zinc-600 italic">
                  No sections parsed yet.
                </div>
              )}
            </>
          )}
        </div>

        {/* Module count */}
        <div className="px-5 py-3 border-t border-zinc-800 text-[11px] text-zinc-600">
          {hasSidebarMode
            ? `${allItems.length} module${allItems.length !== 1 ? "s" : ""} documented`
            : `${sections.length} section${sections.length !== 1 ? "s" : ""} detected`}
        </div>
      </aside>

      {/* ═══════════════════════════════════════════════════ */}
      {/* MAIN CONTENT – Dark Docs Reading Pane               */}
      {/* ═══════════════════════════════════════════════════ */}
      <main className="flex-1 flex flex-col h-full min-w-0 bg-zinc-950">
        {/* Content area */}
        <div className="flex-1 overflow-y-auto px-12 py-10">
          <div className="max-w-3xl mx-auto">
            {/* Breadcrumb */}
            {activeCategoryName && (
              <div className="mb-6 text-xs text-zinc-600">
                <span className="text-zinc-500">{activeCategoryName}</span>
                <span className="mx-1.5 text-zinc-700">/</span>
                <span className="text-zinc-400 font-medium">{activeDisplayTitle}</span>
              </div>
            )}

            {/* Rendered content */}
            {activeContent ? (
              <>
                <article>
                  <style>{`
                    .docs-content h1 { font-size: 26px; font-weight: 700; color: #f4f4f5; margin-bottom: 16px; margin-top: 0; line-height: 1.3; }
                    .docs-content h2 { font-size: 20px; font-weight: 600; color: #e4e4e7; margin-top: 40px; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #27272a; }
                    .docs-content h3 { font-size: 16px; font-weight: 600; color: #d4d4d8; margin-top: 28px; margin-bottom: 8px; }
                    .docs-content p { color: #a1a1aa; margin-bottom: 14px; line-height: 1.75; font-size: 14px; }
                    .docs-content a { color: #60a5fa; text-decoration: none; }
                    .docs-content a:hover { text-decoration: underline; }
                    .docs-content strong { color: #e4e4e7; font-weight: 600; }
                    .docs-content code { background: #27272a; color: #f87171; padding: 2px 6px; border-radius: 4px; font-size: 13px; }
                    .docs-content pre { background: #18181b; border: 1px solid #27272a; border-radius: 8px; padding: 16px 20px; overflow-x: auto; margin: 20px 0; }
                    .docs-content pre code { background: none; color: #a1a1aa; padding: 0; font-size: 13px; }
                    .docs-content table { width: 100%; border-collapse: collapse; margin: 20px 0; font-size: 13px; }
                    .docs-content th { text-align: left; padding: 10px 14px; border-bottom: 1px solid #3f3f46; color: #d4d4d8; font-weight: 600; background: #18181b; }
                    .docs-content td { padding: 10px 14px; border-bottom: 1px solid #27272a; color: #a1a1aa; }
                    .docs-content tr:hover td { background: #1c1c1f; }
                    .docs-content blockquote { border-left: 3px solid #3b82f6; padding: 12px 16px; margin: 20px 0; background: rgba(59,130,246,0.08); border-radius: 0 6px 6px 0; color: #93c5fd; font-size: 13px; }
                    .docs-content blockquote p { margin: 0; color: inherit; }
                    .docs-content ul, .docs-content ol { padding-left: 20px; margin: 12px 0; }
                    .docs-content li { margin-bottom: 6px; color: #a1a1aa; font-size: 14px; }
                    .docs-content li::marker { color: #52525b; }
                    .docs-content hr { border: none; border-top: 1px solid #27272a; margin: 32px 0; }
                    .docs-content img { max-width: 100%; border-radius: 8px; border: 1px solid #27272a; margin: 16px 0; }
                  `}</style>
                  <div className="docs-content">
                    <MarkdownRenderer
                      content={activeContent}
                      includeHeadings
                      includeStandard
                    />
                  </div>
                </article>

                {/* Generated timestamp */}
                {hasSidebarMode && sidebarStructure && (
                  <div className="mt-12 pt-5 border-t border-zinc-800 flex items-center gap-1.5 text-xs text-zinc-600">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <circle cx="12" cy="12" r="10" />
                      <path d="M12 6v6l4 2" />
                    </svg>
                    {/* eslint-disable-next-line i18next/no-literal-string */}
                    <span>Generated {new Date(sidebarStructure.generated_at).toLocaleDateString()}</span>
                  </div>
                )}

                {/* Previous / Next navigation */}
                {hasSidebarMode && (prevItem || nextItem) && (
                  <div className="mt-6 pt-5 border-t border-zinc-800 flex justify-between items-center">
                    {prevItem ? (
                      <button
                        type="button"
                        onClick={() => { setActiveSlug(prevItem.slug); setFeedback(null); }}
                        className="flex items-center gap-2 text-sm text-zinc-500 hover:text-zinc-200 transition-colors"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M19 12H5M12 19l-7-7 7-7" />
                        </svg>
                        {prevItem.title}
                      </button>
                    ) : (
                      <div />
                    )}
                    {nextItem ? (
                      <button
                        type="button"
                        onClick={() => { setActiveSlug(nextItem.slug); setFeedback(null); }}
                        className="flex items-center gap-2 text-sm text-zinc-500 hover:text-zinc-200 transition-colors"
                      >
                        {nextItem.title}
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M5 12h14M12 5l7 7-7 7" />
                        </svg>
                      </button>
                    ) : (
                      <div />
                    )}
                  </div>
                )}

                {/* "Did this page help you?" */}
                <div className="mt-10 pt-6 border-t border-zinc-800 flex items-center justify-center gap-4">
                  <span className="text-sm text-zinc-500">Did this page help you?</span>
                  <button
                    type="button"
                    onClick={() => setFeedback("yes")}
                    className={cn(
                      "flex items-center gap-1.5 text-sm font-medium px-3 py-1 rounded-md transition-colors",
                      feedback === "yes"
                        ? "text-green-400 bg-green-500/10 border border-green-500/20"
                        : "text-zinc-500 hover:text-zinc-300 border border-transparent"
                    )}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M14 9V5a3 3 0 00-3-3l-4 9v11h11.28a2 2 0 002-1.7l1.38-9a2 2 0 00-2-2.3H14zM7 22H4a2 2 0 01-2-2v-7a2 2 0 012-2h3" />
                    </svg>
                    Yes
                  </button>
                  <button
                    type="button"
                    onClick={() => setFeedback("no")}
                    className={cn(
                      "flex items-center gap-1.5 text-sm font-medium px-3 py-1 rounded-md transition-colors",
                      feedback === "no"
                        ? "text-red-400 bg-red-500/10 border border-red-500/20"
                        : "text-zinc-500 hover:text-zinc-300 border border-transparent"
                    )}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M10 15V19a3 3 0 003 3l4-9V2H5.72a2 2 0 00-2 1.7l-1.38 9a2 2 0 002 2.3H10zM17 2h2.67A2.31 2.31 0 0122 4v7a2.31 2.31 0 01-2.33 2H17" />
                    </svg>
                    No
                  </button>
                </div>
              </>
            ) : (
              /* Empty state */
              <div className="text-center py-20">
                <svg
                  width="48"
                  height="48"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1"
                  className="mx-auto mb-4 text-zinc-700"
                >
                  <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                  <polyline points="10 9 9 9 8 9" />
                </svg>
                <p className="text-base font-medium text-zinc-500">
                  {sections.length === 0 && !hasSidebarMode
                    ? "Generate documentation to see content here."
                    : "Select a section from the sidebar."}
                </p>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
