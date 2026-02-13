
import React, { useState, useEffect, useCallback, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Typography } from "#/ui/typography";
import DocumentIcon from "#/icons/document.svg?react";
import { useGitRepositories } from "#/hooks/query/use-git-repositories";
import { useSearchRepositories } from "#/hooks/query/use-search-repositories";
import { Provider } from "#/types/settings";
import { GitRepository } from "#/types/git";

import { cn } from "#/utils/utils";
import { ProjectDocEditor } from "#/components/features/documentation/project-doc-editor";
import { useDocGeneration } from "#/hooks/use-doc-generation";

const MOCK_PROJECTS = [
  { id: "proj1", name: "Frontend Repo", status: "Active" },
  { id: "proj2", name: "Backend API", status: "Pending" },
];

export default function DocumentationDashboard() {
  const { t } = useTranslation();
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [provider, setProvider] = useState<Provider | null>(null);
  const [selectedRepo, setSelectedRepo] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  // --- Doc generation state machine ---
  const docGen = useDocGeneration();

  // Derive booleans from state machine
  const isGenerating = docGen.status === "starting" || docGen.status === "polling";
  const hasGeneratedDocs = docGen.status === "completed";
  const generateError = docGen.error;
  const docContent = docGen.data;

  // --- Standardized repo fetching hooks ---
  // We enable regular fetching only when NOT searching
  const {
    data: repoData,
    isLoading: isLoadingPaged,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useGitRepositories({
    provider,
    enabled: !!provider && !searchQuery,
    pageSize: 50,
  });

  // We enable search fetching only when searching
  const { data: searchData, isLoading: isSearchLoading } =
    useSearchRepositories(searchQuery, provider, !provider, 100);

  // Combined repo list logic
  const repoList = useMemo(() => {
    if (searchQuery) {
      return searchData || [];
    }
    return repoData?.pages?.flatMap((page: { data: GitRepository[] }) => page.data) || [];
  }, [searchQuery, searchData, repoData]);

  const isLoadingRepos = searchQuery ? isSearchLoading : isLoadingPaged;

  // --- Loading step labels ---
  const LOADING_STEPS = useMemo(
    () => [
      "Creating Sandbox Environment...",
      "Cloning Repository...",
      "Analyzing Codebase with Gemini Pro...",
      "Drafting Documentation...",
    ],
    [],
  );

  // Derive loading step from the latest log entry
  const loadingStepIndex = useMemo(() => {
    const lastLog = docGen.logs[docGen.logs.length - 1] ?? "";
    if (lastLog.includes("Documentation Generated")) return 3;
    if (lastLog.includes("Generating")) return 2;
    if (lastLog.includes("Cloning")) return 1;
    return 0;
  }, [docGen.logs]);

  const loadingText = LOADING_STEPS[loadingStepIndex] ?? LOADING_STEPS[0];

  // Elapsed‐time counter
  useEffect(() => {
    if (!isGenerating) {
      setElapsedSeconds(0);
      return undefined;
    }
    const timer = setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [isGenerating]);

  // --- Start generation ---
  const handleGenerateDocs = useCallback(async () => {
    if (!selectedRepo || !provider) return;
    await docGen.startJob(selectedRepo, provider);
  }, [selectedRepo, provider, docGen]);


  const handleProjectSelect = (projectId: string) => {
    setSelectedProject(projectId);
    setProvider(null);
    setSelectedRepo(null);
    setSearchQuery("");
    docGen.reset();
  };

  if (selectedProject) {
    if (isGenerating) {
      const formatTime = (s: number) => {
        const m = Math.floor(s / 60);
        const sec = s % 60;
        return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
      };

      return (
        <div className="h-full w-full bg-zinc-900 flex flex-col items-center justify-center">
          <div className="flex flex-col items-center gap-8 max-w-md w-full px-6">
            {/* Spinner */}
            <div className="relative">
              <div className="w-20 h-20 border-4 border-blue-600/20 rounded-full" />
              <div className="absolute inset-0 w-20 h-20 border-4 border-transparent border-t-blue-500 rounded-full animate-spin" />
              <div className="absolute inset-0 flex items-center justify-center">
                <span className="text-sm font-mono text-blue-400">
                  {formatTime(elapsedSeconds)}
                </span>
              </div>
            </div>

            {/* Current status */}
            <p className="text-xl font-semibold text-zinc-200 text-center animate-pulse">
              {loadingText}
            </p>

            {/* Step progress */}
            <div className="w-full space-y-3">
              {LOADING_STEPS.map((step, idx) => {
                const isDone = idx < loadingStepIndex;
                const isCurrent = idx === loadingStepIndex;
                return (
                  <div
                    key={step}
                    className={cn(
                      "flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm transition-all duration-300",
                      isDone && "bg-green-500/10 text-green-400",
                      isCurrent && "bg-blue-500/10 text-blue-400 ring-1 ring-blue-500/30",
                      !isDone && !isCurrent && "text-zinc-600",
                    )}
                  >
                    {isDone ? (
                      <svg className="w-4 h-4 shrink-0 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                      </svg>
                    ) : isCurrent ? (
                      <div className="w-4 h-4 shrink-0 border-2 border-blue-500/50 border-t-blue-400 rounded-full animate-spin" />
                    ) : (
                      <div className="w-4 h-4 shrink-0 rounded-full border-2 border-zinc-700" />
                    )}
                    <span>{step}</span>
                  </div>
                );
              })}
            </div>

            {/* Hint */}
            <p className="text-xs text-zinc-500 text-center">
              Using Gemini Pro for maximum quality — this may take 1-3 minutes
            </p>
          </div>
        </div>
      );
    }

    if (generateError) {
      return (
        <div className="h-full w-full bg-zinc-900 flex flex-col items-center justify-center p-8">
          <div className="max-w-lg w-full text-center">
            <div className="w-16 h-16 mx-auto mb-6 rounded-full bg-red-500/10 flex items-center justify-center">
              <svg className="w-8 h-8 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
              </svg>
            </div>
            <h3 className="text-xl font-semibold text-white mb-2">Generation Failed</h3>
            <p className="text-zinc-400 mb-6">{generateError}</p>
            <div className="flex gap-4 justify-center">
              <button
                onClick={() => docGen.reset()}
                className="px-6 py-2.5 rounded-lg bg-zinc-800 text-zinc-300 hover:bg-zinc-700 transition-colors"
              >
                ← Back
              </button>
              <button
                onClick={() => { docGen.reset(); handleGenerateDocs(); }}
                className="px-6 py-2.5 rounded-lg bg-blue-600 text-white hover:bg-blue-500 transition-colors"
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      );
    }

    if (!provider) {
      return (
        <div className="h-full w-full bg-zinc-900 overflow-y-auto p-4 md:p-10 flex flex-col items-center justify-center">
          <div className="max-w-4xl w-full">
            <button
              onClick={() => setSelectedProject(null)}
              className="mb-8 text-zinc-400 hover:text-white flex items-center gap-2 transition-colors"
            >
              ← Back to projects
            </button>

            <h2 className="text-3xl font-bold text-zinc-100 mb-10 text-center">
              Connect your repository
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              {/* GitHub Card */}
              <button
                type="button"
                onClick={() => setProvider("github")}
                className={cn(
                  "flex flex-col items-center justify-center p-12 rounded-2xl border-2 transition-all duration-200 group",
                  "bg-zinc-800/50 hover:bg-zinc-800 hover:scale-[1.02]",
                  provider === "github"
                    ? "border-blue-500 ring-2 ring-blue-500/20"
                    : "border-zinc-700 hover:border-zinc-500"
                )}
              >
                <div className="w-24 h-24 mb-6 rounded-full bg-zinc-900 flex items-center justify-center shadow-lg border border-zinc-700 group-hover:border-zinc-600 transition-colors">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="48"
                    height="48"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="text-white"
                  >
                    <path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36.5-8 3C6.72 2 5 2 4.5 3 2 4.5 2 5.5 2 6.5c0 1.25.08 2.45.28 3.5-.27 1.02-.08 2.25 1 3.5-6 3.5-6 5.5-6 5.5"/>
                    <path d="M9 18c-4.51 2-5-2-7-2"/>
                  </svg>
                </div>
                <h3 className="text-2xl font-bold text-white mb-2">GitHub</h3>
                <p className="text-zinc-400 text-center text-lg">
                  Connect to your GitHub repository
                </p>
              </button>

              {/* GitLab Card */}
              <button
                type="button"
                onClick={() => setProvider("gitlab")}
                className={cn(
                  "flex flex-col items-center justify-center p-12 rounded-2xl border-2 transition-all duration-200 group",
                  "bg-zinc-800/50 hover:bg-zinc-800 hover:scale-[1.02]",
                  provider === "gitlab"
                    ? "border-orange-500 ring-2 ring-orange-500/20"
                    : "border-zinc-700 hover:border-zinc-500"
                )}
              >
                <div className="w-24 h-24 mb-6 rounded-full bg-zinc-900 flex items-center justify-center shadow-lg border border-zinc-700 group-hover:border-zinc-600 transition-colors">
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="48"
                    height="48"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="text-orange-500"
                  >
                    <path d="m22 13.29-3.33-10a.42.42 0 0 0-.14-.18.38.38 0 0 0-.22-.11.39.39 0 0 0-.23.07.42.42 0 0 0-.14.18l-2.26 6.67H8.32L6.1 3.26a.42.42 0 0 0-.1-.18.38.38 0 0 0-.26-.08.39.39 0 0 0-.23.07.42.42 0 0 0-.14.18L2 13.29a.74.74 0 0 0 .27.83L12 21l9.69-6.88a.71.71 0 0 0 .31-.83Z"/>
                  </svg>
                </div>
                <h3 className="text-2xl font-bold text-white mb-2">GitLab</h3>
                <p className="text-zinc-400 text-center text-lg">
                  Connect to your GitLab repository
                </p>
              </button>
            </div>
          </div>
        </div>
      );
    }

    if (!hasGeneratedDocs) {
      return (
        <div className="h-full w-full bg-zinc-900 overflow-y-auto p-4 md:p-10 flex flex-col items-center justify-center">
          <div className="max-w-3xl w-full">
            <button
              onClick={() => setProvider(null)}
              className="mb-8 text-zinc-400 hover:text-white flex items-center gap-2 transition-colors"
            >
              ← Back to {provider === "github" ? "GitHub" : "GitLab"}
            </button>

            <h2 className="text-3xl font-bold text-zinc-100 mb-2 text-center">
              Select Repository
            </h2>
            <p className="text-zinc-400 text-center mb-8">
              Choose the repository you want to generate documentation for.
            </p>

            {/* Search */}
            <div className="relative mb-6">
              <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                <svg
                  className="h-5 w-5 text-zinc-500"
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path
                    fillRule="evenodd"
                    d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z"
                    clipRule="evenodd"
                  />
                </svg>
              </div>
              <input
                type="text"
                className="block w-full pl-10 pr-3 py-3 border border-zinc-700 rounded-lg leading-5 bg-zinc-800 text-zinc-300 placeholder-zinc-500 focus:outline-none focus:bg-zinc-900 focus:ring-1 focus:ring-blue-500 focus:border-blue-500 sm:text-sm transition-colors"
                placeholder="Search repositories..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>

            {/* Repo List */}
            <div className="bg-zinc-800/30 border border-zinc-700 rounded-xl overflow-hidden max-h-[400px] overflow-y-auto mb-8">
              {isLoadingRepos ? (
                <div className="p-4 space-y-3">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <div key={i} className="flex items-center gap-3 px-4 py-3 animate-pulse">
                      <div className="w-5 h-5 rounded bg-zinc-700" />
                      <div className="flex-1">
                        <div className="h-4 bg-zinc-700 rounded w-3/4 mb-1" />
                        <div className="h-3 bg-zinc-800 rounded w-1/2" />
                      </div>
                    </div>
                  ))}
                </div>
              ) : repoList.length > 0 ? (
                <ul className="divide-y divide-zinc-700/50">
                  {repoList.map((repo: GitRepository) => (
                    <li key={repo.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedRepo(repo.full_name)}
                        className={cn(
                          "w-full px-6 py-4 flex items-center justify-between text-left transition-colors",
                          selectedRepo === repo.full_name
                            ? "bg-blue-600/10 text-blue-400"
                            : "text-zinc-300 hover:bg-zinc-700/30"
                        )}
                      >
                        <div className="flex flex-col">
                          <span className="font-medium">{repo.full_name}</span>
                          <span className="text-xs text-zinc-500">
                            ID: {repo.id}
                          </span>
                        </div>
                        {selectedRepo === repo.full_name && (
                          <svg
                            className="h-5 w-5 text-blue-500 shrink-0"
                            xmlns="http://www.w3.org/2000/svg"
                            viewBox="0 0 20 20"
                            fill="currentColor"
                          >
                            <path
                              fillRule="evenodd"
                              d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                              clipRule="evenodd"
                            />
                          </svg>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="p-8 text-center text-zinc-500">
                  {searchQuery
                    ? `No repositories found matching "${searchQuery}"`
                    : "No repositories found for this account."}
                </div>
              )}
            </div>

             {/* Action Button */}
             <div className="flex justify-center">
              <button
                type="button"
                disabled={!selectedRepo}
                onClick={handleGenerateDocs}
                className={cn(
                  "px-8 py-4 rounded-xl text-lg font-semibold shadow-lg transition-all duration-200 transform",
                  selectedRepo
                    ? "bg-blue-600 hover:bg-blue-500 text-white hover:scale-[1.02] shadow-blue-900/20"
                    : "bg-zinc-800 text-zinc-500 cursor-not-allowed opacity-50"
                )}
              >
                Generate Documentation
              </button>
            </div>
          </div>
        </div>
      );
    }

    return (
      <ProjectDocEditor
        projectId={selectedProject}
        onBack={() => {
          setSelectedProject(null);
          setProvider(null);
          setSelectedRepo(null);
          setSearchQuery("");
          docGen.reset();
        }}
        initialContent={docContent ?? undefined}
        sidebarStructure={docGen.sidebarStructure}
        documentation={docGen.documentation}
      />
    );
  }

  return (
    <div className="h-full w-full bg-base overflow-y-auto p-4 md:p-10">
      <header className="mb-8">
        <div className="flex items-center gap-3 mb-2">
          <DocumentIcon width={32} height={32} className="text-blue-500" />
          <Typography.H2 className="text-3xl font-bold text-white">
            Documentation Hub
          </Typography.H2>
        </div>
        <Typography.Text className="text-zinc-400">
          Select a project to view its documentation.
        </Typography.Text>
      </header>

      <section>
        <Typography.H3 className="text-xl font-semibold mb-4 text-zinc-200">
          Project Selection
        </Typography.H3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {MOCK_PROJECTS.map((project) => (
            <button
              key={project.id}
              onClick={() => handleProjectSelect(project.id)}
              className={cn(
                "group relative flex flex-col items-start p-6 rounded-xl border border-zinc-800 text-left transition-all duration-200",
                "bg-zinc-900/50 hover:bg-zinc-900 hover:border-zinc-700"
              )}
            >
              <div className="flex justify-between items-start w-full mb-4">
                <div className="p-3 rounded-lg bg-zinc-800 text-zinc-400 group-hover:text-white transition-colors">
                  <DocumentIcon width={24} height={24} />
                </div>
                <span
                  className={cn(
                    "px-2.5 py-1 rounded-full text-xs font-medium",
                    project.status === "Active"
                      ? "bg-green-500/10 text-green-400 border border-green-500/20"
                      : "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20"
                  )}
                >
                  {project.status}
                </span>
              </div>

              <h3 className="text-lg font-semibold text-white mb-2 group-hover:text-blue-400 transition-colors">
                {project.name}
              </h3>
              <p className="text-sm text-zinc-500">
                Project ID: {project.id}
              </p>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
