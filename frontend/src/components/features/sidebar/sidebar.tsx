import React from "react";
import { useLocation, NavLink } from "react-router";

import { useTranslation } from "react-i18next";
import { useGitUser } from "#/hooks/query/use-git-user";
import { UserActions } from "./user-actions";
import { OpenHandsLogoButton } from "#/components/shared/buttons/openhands-logo-button";
import { SettingsModal } from "#/components/shared/modals/settings/settings-modal";
import { useSettings } from "#/hooks/query/use-settings";
import { ConversationPanel } from "../conversation-panel/conversation-panel";
import { ConversationPanelWrapper } from "../conversation-panel/conversation-panel-wrapper";
import { useLogout } from "#/hooks/mutation/use-logout";
import { useConfig } from "#/hooks/query/use-config";
import { displayErrorToast } from "#/utils/custom-toast-handlers";
import { cn } from "#/utils/utils";
import { I18nKey } from "#/i18n/declaration";
import SettingsGearIcon from "#/icons/settings-gear.svg?react";
import PuzzlePieceIcon from "#/icons/u-puzzle-piece.svg?react";
import ListIcon from "#/icons/list.svg?react";
import DocumentIcon from "#/icons/document.svg?react";

export function Sidebar() {
  const { pathname } = useLocation();
  const { t } = useTranslation();
  const user = useGitUser();
  const { data: config } = useConfig();
  const {
    data: settings,
    error: settingsError,
    isError: settingsIsError,
    isFetching: isFetchingSettings,
  } = useSettings();
  const { mutate: logout } = useLogout();

  const [settingsModalIsOpen, setSettingsModalIsOpen] = React.useState(false);

  const [conversationPanelIsOpen, setConversationPanelIsOpen] =
    React.useState(false);

  React.useEffect(() => {
    if (pathname === "/settings") {
      setSettingsModalIsOpen(false);
    } else if (
      !isFetchingSettings &&
      settingsIsError &&
      settingsError?.status !== 404
    ) {
      // We don't show toast errors for settings in the global error handler
      // because we have a special case for 404 errors
      displayErrorToast(
        "Something went wrong while fetching settings. Please reload the page.",
      );
    } else if (
      config?.APP_MODE === "oss" &&
      settingsError?.status === 404 &&
      !config?.FEATURE_FLAGS?.HIDE_LLM_SETTINGS
    ) {
      setSettingsModalIsOpen(true);
    }
  }, [
    pathname,
    isFetchingSettings,
    settingsIsError,
    settingsError,
    config?.APP_MODE,
    config?.FEATURE_FLAGS?.HIDE_LLM_SETTINGS,
  ]);

  return (
    <>
      <aside
        className={cn(
          "h-[54px] p-3 md:p-0 md:h-[40px] md:h-auto flex flex-row md:flex-col gap-1 bg-[#09090b] border-r border-zinc-800 md:w-[200px] md:min-w-[200px] sm:pt-0 sm:px-2 md:pt-6 md:px-3",
          pathname === "/" && "md:pt-6 md:pb-3",
        )}
      >
        <nav className="flex flex-row md:flex-col items-center md:items-stretch justify-between w-full h-auto md:w-auto md:h-full">
          <div className="flex flex-row md:flex-col items-center md:items-stretch gap-6">
            {/* Logo */}
            <div className="w-full mb-4">
              <OpenHandsLogoButton />
            </div>

            {/* New Project Button */}
            <NavLink
              to="/"
              data-testid="new-project-button"
              aria-label={t(I18nKey.CONVERSATION$START_NEW)}
              tabIndex={settings?.email_verified === false ? -1 : 0}
              onClick={(e) => {
                if (settings?.email_verified === false) {
                  e.preventDefault();
                }
              }}
              className={cn(
                "w-full flex items-center justify-center md:justify-start gap-3 px-3 py-2.5 rounded-lg",
                "bg-blue-600 hover:bg-blue-500 text-white font-medium text-sm",
                settings?.email_verified === false &&
                  "pointer-events-none opacity-50",
              )}
            >
              <span className="text-lg leading-none">+</span>
              <span className="hidden md:block">
                {t(I18nKey.CONVERSATION$START_NEW)}
              </span>
            </NavLink>

            {/* Conversations Button */}
            <button
              type="button"
              onClick={() => {
                if (settings?.email_verified !== false) {
                  setConversationPanelIsOpen((prev) => !prev);
                }
              }}
              className={cn(
                "w-full flex items-center justify-center md:justify-start gap-3 px-3 py-2.5 rounded-lg",
                conversationPanelIsOpen
                  ? "bg-zinc-800 text-blue-500"
                  : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200",
                settings?.email_verified === false &&
                  "pointer-events-none opacity-50",
              )}
              tabIndex={settings?.email_verified === false ? -1 : 0}
            >
              <ListIcon width={20} height={20} />
              <span className="hidden md:block text-sm font-medium">
                {t(I18nKey.SIDEBAR$CONVERSATIONS)}
              </span>
            </button>

            {/* Integrations Link */}
            <NavLink
              to="/integrations"
              className={({ isActive }) =>
                cn(
                  "w-full flex items-center justify-center md:justify-start gap-3 px-3 py-2.5 rounded-lg",
                  isActive
                    ? "bg-zinc-800 text-blue-500"
                    : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200",
                  settings?.email_verified === false &&
                    "pointer-events-none opacity-50",
                )
              }
              tabIndex={settings?.email_verified === false ? -1 : 0}
              onClick={(e) => {
                if (settings?.email_verified === false) {
                  e.preventDefault();
                }
              }}
            >
              <PuzzlePieceIcon width={20} height={20} />
              <span className="hidden md:block text-sm font-medium">
                {t(I18nKey.SETTINGS$NAV_INTEGRATIONS)}
              </span>
            </NavLink>

            {/* Documentation Link */}
            <NavLink
              to="/documentation"
              className={({ isActive }) =>
                cn(
                  "w-full flex items-center justify-center md:justify-start gap-3 px-3 py-2.5 rounded-lg",
                  isActive
                    ? "bg-zinc-800 text-blue-500"
                    : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200",
                  settings?.email_verified === false &&
                    "pointer-events-none opacity-50",
                )
              }
              tabIndex={settings?.email_verified === false ? -1 : 0}
              onClick={(e) => {
                if (settings?.email_verified === false) {
                  e.preventDefault();
                }
              }}
            >
              <DocumentIcon width={20} height={20} />
              <span className="hidden md:block text-sm font-medium">
                {t(I18nKey.SIDEBAR$DOCS)}
              </span>
            </NavLink>

            {/* Settings Link */}
            <NavLink
              to="/settings"
              className={({ isActive }) =>
                cn(
                  "w-full flex items-center justify-center md:justify-start gap-3 px-3 py-2.5 rounded-lg",
                  isActive
                    ? "bg-zinc-800 text-blue-500"
                    : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200",
                  settings?.email_verified === false &&
                    "pointer-events-none opacity-50",
                )
              }
              tabIndex={settings?.email_verified === false ? -1 : 0}
              onClick={(e) => {
                if (settings?.email_verified === false) {
                  e.preventDefault();
                }
              }}
            >
              <SettingsGearIcon width={20} height={20} />
              <span className="hidden md:block text-sm font-medium">
                {t(I18nKey.SETTINGS$TITLE)}
              </span>
            </NavLink>


          </div>

          <div className="flex flex-row md:flex-col md:items-stretch gap-6">
            <UserActions
              user={
                user.data ? { avatar_url: user.data.avatar_url } : undefined
              }
              onLogout={logout}
              isLoading={user.isFetching}
              onOpenConversations={() =>
                setConversationPanelIsOpen((prev) => !prev)
              }
              conversationPanelIsOpen={conversationPanelIsOpen}
              emailVerified={settings?.email_verified}
            />
          </div>
        </nav>

        {conversationPanelIsOpen && (
          <ConversationPanelWrapper isOpen={conversationPanelIsOpen}>
            <ConversationPanel
              onClose={() => setConversationPanelIsOpen(false)}
            />
          </ConversationPanelWrapper>
        )}
      </aside>

      {settingsModalIsOpen && (
        <SettingsModal
          settings={settings}
          onClose={() => setSettingsModalIsOpen(false)}
        />
      )}
    </>
  );
}
