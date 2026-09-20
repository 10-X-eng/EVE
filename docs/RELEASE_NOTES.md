# EVE 0.2.0 — Images, tool activity, and updates

This update fixes screenshot paste in Fusion and adds saved chat image lookup, visible tool activity, and update notifications with verified downloads.

## What changed

- **Screenshot paste works through the native clipboard.** Windows users have confirmed the fix for issue #1. Plain text paste and file attachments continue to work. The macOS clipboard implementation still needs live confirmation.
- **Revisit pictures from a chat.** EVE can list and reopen indexed attachments and historical viewport captures, including after restarting and reopening a conversation. Older, unindexed pictures need reattaching.
- **See which tool is active.** The composer shows the current Fusion or saved-image tool and operation title, including waiting and overlapping calls.
- **A shorter core prompt.** Detailed API recipes are returned when relevant, keeping the main instructions focused on the task.
- **Update notifications and downloads.** EVE checks on startup and every 12 hours while running. Download the appropriate package to Downloads with progress and SHA-256 verification, then install when ready. The account menu provides a manual check.
- **Windows and Apple silicon Mac packages.** Both packages must build and pass verification before the release is published.

## Update or install

- **Windows x64:** download **EVE-0.2.0-windows-x64.zip**, extract the whole ZIP, close Fusion, then run **Install EVE.exe**.
- **macOS (Apple silicon):** download **EVE-0.2.0-macos-arm64.zip**, extract it, quit Fusion, then run **Install EVE.command** through Terminal (type `bash `, drag the file in, press Return) or allow it under System Settings > Privacy & Security.

Users of 0.1.0 must install this update manually once to receive future in-app update notices. Existing sign-in, chat history, preferences, and cached images are stored separately and preserved by the installer. Start a new conversation once after upgrading to register the new image tools.

Each ZIP includes the Codex runtime, installer, and installation guide. GitHub's **Source code** downloads do not include the runtime or installer. EVE downloads updates on request and does not replace files while Fusion is running.

These are unsigned previews. Live Fusion verification is ongoing; see the repository's verification notes. Each package's SHA-256 checksum is included as a separate release asset.
