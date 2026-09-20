# Install EVE for Autodesk Fusion

EVE 0.1.0 is a preview for Windows x64 and macOS on Apple silicon. You need Autodesk Fusion, an internet connection, and a ChatGPT account with Codex access. Each complete package includes Codex; no separate Python, Node.js, API key, or EVE account is required.

Download the package for your computer from the [EVE releases page](https://github.com/10-X-eng/EVE/releases): `EVE-0.1.0-windows-x64.zip` or `EVE-0.1.0-macos-arm64.zip`. Use the packaged zip, not GitHub's **Source code** download, which does not include the runtime. If no release is listed, a maintainer must build the package first.

## Install on Windows

1. Right-click the zip and choose **Extract All**. Keep the entire extracted folder together, including `Install EVE.exe`, `SHA256SUMS`, and the `EVE` folder.
2. Save your work and close Fusion.
3. Open **Install EVE.exe** and click **Install EVE**. Installation is for your current Windows account and does not need administrator access. This preview's installer is unsigned.
4. Open Fusion. Open **Scripts and Add-ins** (Design workspace: **Utilities > Add-ins**), select the **Add-ins** tab, select **EVE**, and click **Run**. Enable **Run on Startup** if you want EVE available every time you open Fusion.
5. Click **EVE** in the **Quick Access toolbar** at the top of Fusion. It is also available through command search.
6. Click **Sign in with ChatGPT**, finish in your browser, and return to Fusion. Existing EVE sign-in is checked automatically.

To verify the download, run `Get-FileHash .\EVE-0.1.0-windows-x64.zip -Algorithm SHA256` in PowerShell from the download folder and compare it with the accompanying `.zip.sha256` file.

## Install on macOS

1. Double-click the zip to extract it. Keep the extracted folder together, including `Install EVE.command`, `SHA256SUMS`, and the `EVE` folder.
2. Save your work and quit Fusion.
3. Open Terminal, type `bash ` (with a trailing space), drag **Install EVE.command** from Finder into the Terminal window, and press Return. Installation is for your current macOS account and does not need administrator access.
   Double-clicking **Install EVE.command** also works, but because this preview is not signed, macOS blocks it the first time. Open **System Settings > Privacy & Security**, choose **Open Anyway** next to the message about the installer, and confirm.
4. Open Fusion. Open **Scripts and Add-ins** (Design workspace: **Utilities > Add-ins**), select the **Add-ins** tab, select **EVE**, and click **Run**. Enable **Run on Startup** if you want EVE available every time you open Fusion.
5. Click **EVE** in the **Quick Access toolbar** at the top of Fusion. It is also available through command search.
6. Click **Sign in with ChatGPT**, finish in your browser, and return to Fusion. Existing EVE sign-in is checked automatically.

To verify the download, run `shasum -a 256 EVE-0.1.0-macos-arm64.zip` in Terminal from the download folder and compare it with the accompanying `.zip.sha256` file. The bundled Codex binaries are signed and notarized by OpenAI.

## First conversation

Open a design and start with: **“Inspect this document and summarize its components and parameters.”** Then ask for the change you want, including dimensions and units. Save the design before trying generated operations.

- Select geometry before sending to give EVE context about “this.”
- Use the paperclip beside Send, or paste into the message box (Ctrl+V on Windows, ⌘V on macOS), to attach reference images.
- Choose a model and effort beside Send. EVE remembers those preferences.
- Send another message to steer a running task. **Stop** cancels pending work; a long native Fusion operation may need to finish first.
- Use the history icon to reopen saved conversations.

A running task keeps its starting document and selection. If you switch documents, pending Fusion calls wait until you return. There is one active conversation per Fusion instance.

## Update or reload

For a packaged update, close Fusion and install the new complete package. The installer preserves the previous managed add-in under `EVE-install-backups` beside the `AddIns` folder: `%APPDATA%\Autodesk\Autodesk Fusion 360\API` on Windows, `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API` on macOS. Sign-in, history, and preferences are kept separately.

For a development checkout, use **Stop**, then **Run** in Scripts and Add-ins after source changes. Start a new conversation after tool definitions change.

## Troubleshooting

- **EVE is not listed:** use the add-in folder selection in Scripts and Add-ins to select the `EVE` folder under `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns` (Windows) or `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns` (macOS), then Run.
- **macOS says the installer cannot be opened:** run it through Terminal as described above, or allow it under System Settings > Privacy & Security.
- **Installer reports an unmanaged EVE folder:** preserve or rename your existing manually installed folder before installing. The installer will not overwrite it.
- **Sign-in does not finish:** return to EVE and choose **Check again**, or use the device-code sign-in option. Use the ChatGPT account that has Codex access.
- **Codex setup needed:** extract and reinstall the complete EVE package for your platform. Installing Codex separately does not replace EVE's required bundled files. If EVE reports that Codex lost its run permission, run the installer again instead of copying the `EVE` folder by hand.
- **An operation fails:** enable **Debug logging** in the account menu, reproduce the problem, then choose **Open logs folder**. Review logs for private design information before sharing them.

EVE's local sign-in, history, preferences, image cache, and optional logs are under `%LOCALAPPDATA%\EVE` on Windows and `~/Library/Application Support/EVE` on macOS. These chats do not sync to the ChatGPT website.

## Uninstall

Close Fusion and remove only the `EVE` folder under the `AddIns` folder named above. Local account data and history remain under EVE's data folder; remove that separate folder only if you also want to erase EVE's saved local data.
