import { useState, useRef, useEffect, useCallback } from 'react';

export type DocGenStatus = 'idle' | 'starting' | 'polling' | 'completed' | 'failed';

// Sidebar structure types matching backend output
export interface SidebarItem {
  title: string;
  slug: string;
  route?: string;
  persona?: string;
  description?: string;
  probed_tabs?: number;
  probed_buttons?: number;
  probed_modals?: number;
}

export interface SidebarCategory {
  name: string;
  icon: string;
  description?: string;
  items: SidebarItem[];
}

export interface SidebarStructure {
  project_name: string;
  project_type: string;
  generated_at: string;
  categories: SidebarCategory[];
}

export const useDocGeneration = () => {
  const [status, setStatus] = useState<DocGenStatus>('idle');
  const [jobId, setJobId] = useState<string | null>(null);
  const [data, setData] = useState<string | null>(null);
  const [sidebarStructure, setSidebarStructure] = useState<SidebarStructure | null>(null);
  const [documentation, setDocumentation] = useState<Record<string, string> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [logs, setLogs] = useState<string[]>([]);

  // Ref to prevent overlapping requests
  const isRequestPending = useRef(false);

  const startJob = async (repoName: string, provider: string) => {
    setStatus('starting');
    setError(null);
    setData(null);
    setSidebarStructure(null);
    setDocumentation(null);
    setLogs(['Initializing Agent...']);

    try {
      const res = await fetch('/api/generate-docs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_name: repoName, provider }),
      });
      const json = await res.json();

      if (json.job_id) {
        setJobId(json.job_id);
        setStatus('polling');
        setLogs(prev => [...prev, 'Job started. Analyzing Codebase...']);
      } else {
        setError(json.error || json.detail || 'Failed to start job');
        setStatus('failed');
      }
    } catch (e) {
      console.error(e);
      setError(e instanceof Error ? e.message : 'Failed to start generation');
      setStatus('failed');
    }
  };

  useEffect(() => {
    let intervalId: NodeJS.Timeout;

    if (status === 'polling' && jobId) {
      intervalId = setInterval(async () => {
        if (isRequestPending.current) return;

        isRequestPending.current = true;
        try {
          const res = await fetch(`/api/generate-docs/${jobId}`);
          const json = await res.json();

          if (json.status === 'completed') {
            setData(json.markdown);
            // Capture sidebar structure and per-module docs
            if (json.sidebar_structure) {
              setSidebarStructure(json.sidebar_structure);
            }
            if (json.documentation) {
              setDocumentation(json.documentation);
            }
            setStatus('completed');
            setLogs(prev => [...prev, 'Documentation Generated!']);
          } else if (json.status === 'failed') {
            setError(json.error || 'Documentation generation failed.');
            setStatus('failed');
          } else if (json.status === 'not_found') {
            setError('Job not found on server.');
            setStatus('failed');
          } else {
            if (json.status === 'cloning') {
              setLogs(prev => {
                if (prev[prev.length - 1] !== 'Cloning Repository...') {
                  return [...prev, 'Cloning Repository...'];
                }
                return prev;
              });
            } else if (json.status === 'generating') {
              setLogs(prev => {
                if (prev[prev.length - 1] !== 'Generating with Gemini Pro...') {
                  return [...prev, 'Generating with Gemini Pro...'];
                }
                return prev;
              });
            }
          }
        } catch (e) {
          console.error("Polling error", e);
        } finally {
          isRequestPending.current = false;
        }
      }, 5000);
    }

    return () => clearInterval(intervalId);
  }, [status, jobId]);

  const reset = useCallback(() => {
    setStatus('idle');
    setJobId(null);
    setData(null);
    setSidebarStructure(null);
    setDocumentation(null);
    setError(null);
    setLogs([]);
    isRequestPending.current = false;
  }, []);

  return { status, startJob, data, sidebarStructure, documentation, error, logs, reset };
};
