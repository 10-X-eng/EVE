# Install EVE for Autodesk Fusion

EVE 0.1.0 is a Windows x64 preview. You need Autodesk Fusion, an internet connection, and a ChatGPT account with Codex access. The complete package includes Codex; no separate Python, Node.js, API key, or EVE account is required.

## Install

1. Download `EVE-0.1.0-windows-x64.zip` from the [EVE releases page](https://github.com/10-X-eng/EVE/releases). Use the packaged zip, not GitHub's **Source code** download, which does not include the runtime. If no release is listed, a maintainer must build the package first.
2. Right-click the zip and choose **Extract All**. Keep the entire extracted folder together, including `Install EVE.exe`, `SHA256SUMS`, and the `EVE` folder.
3. Save your work and close Fusion.
4. Open **Install EVE.exe** and click **Install EVE**. Installation is for your current Windows account and does not need administrator access. This preview's installer is unsigned.
5. Open Fusion. Open **Scripts and Add-ins** (Design workspace: **Utilities > Add-ins**), select the **Add-ins** tab, select **EVE**, and click **Run**. Enable **Run on Startup** if you want EVE available every time you open Fusion.
6. Click **EVE** in the **Quick Access toolbar** at the top of Fusion. It is also available through command search.
7. Click **Sign in with ChatGPT**, finish in your browser, and return to Fusion. Existing EVE sign-in is checked automatically.

To verify the download, run `Get-FileHash .\EVE-0.1.0-windows-x64.zip -Algorithm SHA256` in PowerShell from the download folder and compare it with the accompanying `.zip.sha256` file.

## First conversation

Open a design and start with: **“Inspect this document and summarize its components and parameters.”** Then ask for the change you want, including dimensions and units. Save the design before trying generated operations.

- Select geometry before sending to give EVE context about “this.”
- Use the paperclip beside Send, or paste into the message box, to attach reference images.
- Choose a model and effort beside Send. EVE remembers those preferences.
- Send another message to steer a running task. **Stop** cancels pending work; a long native Fusion operation may need to finish first.
- Use the history icon to reopen saved conversations.

A running task keeps its starting document and selection. If you switch documents, pending Fusion calls wait until you return. There is one active conversation per Fusion instance.

## Update or reload

For a packaged update, close Fusion and install the new complete package. The installer preserves the previous managed add-in under `%APPDATA%\Autodesk\Autodesk Fusion 360\API\EVE-install-backups`. Sign-in, history, and preferences are kept separately.

For a development checkout, use **Stop**, then **Run** in Scripts and Add-ins after source changes. Start a new conversation after tool definitions change.

## Troubleshooting

- **EVE is not listed:** use the add-in folder selection in Scripts and Add-ins to select `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns\EVE`, then Run.
- **Installer reports an unmanaged EVE folder:** preserve or rename your existing manually installed folder before installing. The installer will not overwrite it.
- **Sign-in does not finish:** return to EVE and choose **Check again**, or use the device-code sign-in option. Use the ChatGPT account that has Codex access.
- **Codex setup needed:** extract and reinstall the complete EVE package. Installing Codex separately does not replace EVE's required bundled files.
- **An operation fails:** enable **Debug logging** in the account menu, reproduce the problem, then choose **Open logs folder**. Review logs for private design information before sharing them.

EVE's local sign-in, history, preferences, image cache, and optional logs are under `%LOCALAPPDATA%\EVE`. These chats do not sync to the ChatGPT website.

## Uninstall

Close Fusion and remove only the `EVE` folder under `%APPDATA%\Autodesk\Autodesk Fusion 360\API\AddIns`. Local account data and history remain under `%LOCALAPPDATA%\EVE`; remove that separate folder only if you also want to erase EVE's saved local data.
