export const MAP_MODEL: Record<string, string> = {
  // Explicit requests
  "gemini-3.1-pro": "Gemini 3.1 Pro",
  "gemini-3.1-flash": "Gemini 3.1 Flash",
  "gemini-3.1-flash-lite": "Gemini 3.1 Flash-Lite",
  "gemini-3-deep-think": "Gemini 3 Deep Think",
  "gemini-2.5-pro": "Gemini 2.5 Pro",
  "gemini-2.5-flash": "Gemini 2.5 Flash",
  "gemini-2.5-flash-live": "Gemini 2.5 Flash Live",
  "gemini-1.5-pro": "Gemini 1.5 Pro",
  "gemini-1.5-flash": "Gemini 1.5 Flash",
  "gemini-1.5-flash-8b": "Gemini 1.5 Flash 8B",
  "gemini-2.0-flash": "Gemini 2.0 Flash",
  "gemini-2.0-flash-lite": "Gemini 2.0 Flash Lite",
  "gemini-2.0-pro-exp": "Gemini 2.0 Pro Exp",

  // Other knowns
  "gpt-4o": "GPT-4o",
  "gpt-4o-mini": "GPT-4o Mini",
  "gpt-5.2": "GPT 5.2",
  "gpt-5.2-codex": "GPT 5.2 Codex",
  "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet (20241022)",
  "claude-3-7-sonnet-20250219": "Claude 3.7 Sonnet (20250219)",
  "claude-sonnet-4-20250514": "Claude Sonnet 4 (20250514)",
  "claude-sonnet-4-5-20250929": "Claude Sonnet 4.5 (20250929)",
  "claude-haiku-4-5-20251001": "Claude Haiku 4.5 (20251001)",
  "claude-opus-4-20250514": "Claude Opus 4 (20250514)",
  "claude-opus-4-1-20250805": "Claude Opus 4.1 (20250805)",
  "claude-opus-4-5-20251101": "Claude Opus 4.5 (20251101)",
  "o3-mini-2025-01-31": "o3 Mini",
  "o3-2025-04-16": "o3",
  "o3": "o3",
  "o4-mini-2025-04-16": "o4 Mini",
  "o4-mini": "o4 Mini",
  "deepseek-chat": "DeepSeek Chat",
};

export const formatModelName = (modelId: string): string => {
  if (MAP_MODEL[modelId]) {
    return MAP_MODEL[modelId];
  }

  // Automatic formatting fallback
  return modelId
    .split(/[-_]+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ")
    .replace(/Gpt/i, "GPT")
    .replace(/Claude/i, "Claude")
    .replace(/Gemini/i, "Gemini");
};
