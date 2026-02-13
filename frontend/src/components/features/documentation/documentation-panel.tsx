import React from "react";
import { useTranslation } from "react-i18next";
import { cn } from "#/utils/utils";

import { I18nKey } from "#/i18n/declaration";

export function DocumentationPanel() {
  const { t } = useTranslation();

  return (
    <div className="flex flex-col h-full w-full bg-zinc-900">
      <div className="flex items-center justify-between p-4 border-b border-zinc-700">
        <h2 className="text-lg font-semibold text-zinc-100">
          {t(I18nKey.SIDEBAR$DOCS)}
        </h2>
        <button
          type="button"
          onClick={() => {
            // Action to maximize/generate docs later
          }}
          className={cn(
            "px-4 py-2 rounded-lg text-sm font-medium transition-colors",
            "bg-blue-600 hover:bg-blue-500 text-white shadow-sm",
          )}
        >
          {/* eslint-disable-next-line i18next/no-literal-string */}
          Generate Workspace Docs
        </button>
      </div>
      <div className="flex-1 w-full p-4 overflow-auto">
        <div className="h-full border-2 border-dashed border-zinc-700 rounded-lg flex items-center justify-center text-zinc-500">
          {/* eslint-disable-next-line i18next/no-literal-string */}
          Documentation content will appear here...
        </div>
      </div>
    </div>
  );
}
