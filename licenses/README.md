The Windows and macOS packages include unmodified OpenAI Codex app-server 0.153.4, its Code Mode host, and the helper programs shipped in the same upstream package (`rg`; on macOS also `zsh`). Those helpers keep their own upstream licenses.

`CODEX-LICENSE.txt` reproduces the license from the [pinned upstream release](https://github.com/openai/codex/blob/rust-v0.153.4/LICENSE). Text was retrieved from that source; whitespace may differ.

STEVE's own source code and documentation are licensed under the [MIT License](../LICENSE). The MIT license does not replace the licenses of the third-party components described here. Release packages include STEVE's license at the package root and in the installed add-in.

The Claude transport adapts Nous Research's [Hermes Claude subscription plugin](https://github.com/NousResearch/hermes-plugin-claude-subscription-directsdk) at commit `f1c1220778c7864fe4c1494baf9b1566e7c95bd2` under MIT. Its copyright notice, full license, and modification notes ship in `steve/claude_native/` inside the add-in. The official Claude Code executable is installed separately by the user and is not redistributed by STEVE.
