# Tool description contract

Descriptions should contain the information needed to choose and correctly call a
tool. Keep each fact where the model needs it: purpose and prerequisites in the
function description; argument meaning, provenance and defaults in the schema;
execution recipes in explicitly linked API help; corrective action in errors.
Removing words is not a goal if it removes a necessary distinction.

The shared core prompt retains targeting, authorization, verification and recovery
rules. Do not repeat those paragraphs in every tool. Python-context details are
available through the existing `fusion_api_help` tool at `steve.python`, alongside
`steve.helpers` and `steve.dfm[.<process>]`. This adds a help path, not a tool.

## Reviewed contracts

The following distinctions were checked against the handlers and validators:

| Tool | Essential calling distinctions |
| --- | --- |
| `rmfg_checkout` | Quote saved checked jobs and quantities in one pinned document; status/create use returned `checkoutId`; quote retries reuse that receipt; status pages findings; creation checks quote identity, settings and current snapshots, then exposes a hosted checkout button without payment |
| `rmfg_materials` | DFM enabled and connection required; catalog IDs configure supplier checks; omit cursor first, then use `next_cursor` while `has_more` |
| `fusion_rmfg` | Pinned target and sheet-metal plan; prepare exports and automatically uploads the scoped part; other actions require `job_id` from returned `jobId`; status pages with `nextOffset`; check requires ready analysis and every part/material pair; retry reuses stored bytes; reports remain snapshot evidence |
| `fusion_dfm_plan` | Omitted stages reads; a supplied complete ordered plan replaces; `[]` clears only on user request; native repeated parts share metadata; persistence differs for saved/unsaved documents |
| `fusion_dfm_check` | Read-only code, an existing zero-based plan stage, helper-recorded findings and report scope; successful execution is not a manufacturing pass |
| `fusion_search_docs` | Installed names/docstrings versus sample titles; installed scope defaults; sample index may download but query stays local; continue returned offsets |
| `fusion_fetch_docs` | Exact Autodesk `.htm` URL scope without query/fragment; character offsets; online references must be checked against the installed API |
| `list_chat_images` | Current chat only; metadata and `imageId`, not pixels; paging defaults; missing historical images require reattachment |
| `view_chat_image` | `image_id` comes from listed `imageId`; delivers saved pixels rather than a fresh capture; `imageDelivered` confirms delivery |
| `fusion_capture_viewport` | Pinned document; current view for other products, named views/close-ups for Design/CAM; mutually exclusive captured selection index or entity token; temporary camera handling |
| `fusion_inspect_document` | Pinned summary/captured context; active document only without a pinned task; document identifier remains available when no document is open |
| `fusion_query_python` | Read-only inspection versus mutation; pinned document ID; script entry point and help; bounded/paged JSON and truncation recovery |
| `fusion_execute_python` | Authorized changes versus inspection; command/application execution semantics and default; bounded results; inspect uncertain outcomes before repeating writes |
| `fusion_api_help` | Installed namespace/class/member lookup versus exact STEVE help paths; no native method invocation |

Runtime validation remains authoritative. Schema defaults describe actual handler
defaults; action-specific optional fields are not accepted on unrelated actions.
The review corrected unclear field naming, zero-based indices, URL restrictions
and product-specific viewport support rather than merely shortening prose.

## Verification and limits

A real local Codex 0.153.4 process with a loopback inference fixture retained its
original dynamic tools despite replacement lists supplied on resume, including
after a fresh process. Therefore STEVE keeps its DFM/supplier tools
registered, with execution gated by the DFM switch. It does not silently fork or
rewrite existing chats. This is observed behavior of that installed version,
not a claim that every future runtime must behave identically. OpenAI documents
dynamic-tool persistence in its [app-server reference](https://learn.chatgpt.com/docs/app-server).
Reload the source add-in and start a new chat to use revised tool descriptions.
Existing chats retain their registered descriptions; their history is not rewritten.

The original description audit kept the core prompt and 13-tool inventory unchanged.
The checkout workflow adds `rmfg_checkout`, for 14 tools total. The repeated Python-context
paragraph moved out of three descriptions into one on-demand reference. Serialized
schema character counts are recorded in the DFM evaluation; they are not a claim
about a provider's tokenizer, full context window or latency.

Unit/runner tests verify the help route without API imports or execution, input
validation and existing tool behavior. Real-model, read-only Fusion trials with
DFM off/on exercise help discovery and measured findings. They establish those
workflows, not proof that every possible request is unambiguous or that shorter
descriptions necessarily improve model quality. Future edits need behavioral
evidence, not a test that simply asserts a word count or repeats the prose.
