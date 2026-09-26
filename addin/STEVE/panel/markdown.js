/* Safe Markdown and code rendering for replies. Every text run is escaped; no model HTML passes through. */
"use strict";
const SteveMarkdown = (() => {
  const escape = text => String(text).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  // Links are validated on the unescaped URL, so quotes never reach an href even in escaped form.
  const WEB_URL = /^https?:\/\/[^\s<>"'`]+$/i;
  const webURL = escaped => WEB_URL.test(escaped.replace(/&quot;|&#39;/g, '"'));

  // --- Syntax highlighting. Spans wrap the exact source text, so textContent still equals the code.
  const PY_KEYWORDS = new Set(("False None True and as assert async await break class continue def del elif else except " +
    "finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case").split(" "));
  const PY_BUILTINS = new Set(("abs all any bool bytes callable chr dict dir divmod enumerate filter float format frozenset " +
    "getattr hasattr hash hex id int isinstance issubclass iter len list map max min next object oct open ord pow print " +
    "property range repr reversed round set setattr slice sorted staticmethod classmethod str sum super tuple type vars zip " +
    "Exception ValueError TypeError RuntimeError AttributeError KeyError IndexError StopIteration").split(" "));
  const PY_RULES = [
    [/#[^\n]*/y, "cm"],
    [/(?:[rRbBuUfF]{1,2})?(?:"""[\s\S]*?"""|'''[\s\S]*?'''|"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')/y, "str"],
    [/(?:[rRbBuUfF]{1,2})?(?:"""[\s\S]*|'''[\s\S]*|"[^\n]*|'[^\n]*)/y, "str"],
    [/@[A-Za-z_][\w.]*/y, "dec"],
    [/\b(?:0[xXoObB][\da-fA-F_]+|\d[\d_]*(?:\.[\d_]*)?(?:[eE][+-]?\d+)?j?)\b/y, "num"],
    [/[A-Za-z_]\w*/y, "id"],
    [/\s+/y, "ws"],
    [/[^\sA-Za-z_0-9#"'@]+/y, "op"],
    [/[\s\S]/y, "op"],
  ];
  function highlightPython(code) {
    let out = "", i = 0, previous = "";
    while (i < code.length) {
      for (const [rule, cls] of PY_RULES) {
        rule.lastIndex = i;
        const match = rule.exec(code);
        if (!match || match.index !== i || !match[0]) continue;
        const text = match[0];
        let kind = cls;
        if (cls === "id") {
          if (PY_KEYWORDS.has(text)) kind = "kw";
          else if (previous === "def" || previous === "class") kind = "fn";
          else if (text === "self" || text === "cls") kind = "self";
          else if (PY_BUILTINS.has(text)) kind = "bi";
          else if (code[i + text.length] === "(") kind = "call";
          else kind = "";
          previous = text;
        } else if (cls !== "ws" && cls !== "cm") previous = "";
        out += kind && kind !== "ws" && kind !== "op" ? `<span class="tok-${kind}">${escape(text)}</span>` : escape(text);
        i += text.length;
        break;
      }
    }
    return out;
  }
  function highlightJSON(code) {
    return escape(code).replace(/(&quot;(?:[^&]|&(?!quot;))*?&quot;)(\s*:)?|\b(true|false|null)\b|(-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)/g,
      (all, string, key, literal, number) => string ? `<span class="${key ? "tok-key" : "tok-str"}">${string}</span>${key || ""}`
        : literal ? `<span class="tok-kw">${literal}</span>` : `<span class="tok-num">${number}</span>`);
  }
  function highlight(code, language) {
    const lang = String(language || "").toLowerCase();
    if (lang === "python" || lang === "py" || lang === "python3") return highlightPython(code);
    if (lang === "json") return highlightJSON(code);
    return escape(code);
  }
  function codeBlock(code, language) {
    const lang = String(language || "").toLowerCase().replace(/[^a-z0-9+#.-]/g, "").slice(0, 20);
    const label = {py: "Python", python: "Python", python3: "Python", json: "JSON", js: "JavaScript", javascript: "JavaScript",
      sh: "Shell", bash: "Shell", powershell: "PowerShell", txt: "Text", text: "Text"}[lang] || (lang ? lang.toUpperCase() : "");
    return `<div class="code-block"><div class="code-tools"><span class="code-lang">${escape(label)}</span>` +
      `<button type="button" class="copy-code">Copy</button></div><pre><code>${highlight(code, lang)}</code></pre></div>`;
  }

  // --- Inline Markdown. Code spans and links become placeholders so later passes cannot rewrite them.
  function inline(text) {
    const saved = [];
    const keep = html => { saved.push(html); return `\u0000${saved.length - 1}\u0000`; };
    let out = String(text).replace(/(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)/g, (all, ticks, code) => keep(`<code>${escape(code.trim())}</code>`));
    out = escape(out);
    out = out.replace(/\[([^\]\n]+)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g, (all, label, url) =>
      webURL(url) ? keep(`<a href="${url}">${label}</a>`) : all);
    out = out.replace(/&lt;(https?:\/\/[^\s&]+)&gt;/g, (all, url) => keep(`<a href="${url}">${url}</a>`));
    out = out.replace(/(^|[\s(])(https?:\/\/[^\s<>()]*[^\s<>().,;:!?'"])/g, (all, lead, url) =>
      lead + (webURL(url) ? keep(`<a href="${url}">${url}</a>`) : url));
    out = out.replace(/\*\*([^*\n]+?)\*\*|__([^_\n]+?)__/g, (all, a, b) => `<strong>${a ?? b}</strong>`)
      .replace(/(^|[^*\w])\*([^*\n]+?)\*(?!\w)/g, "$1<em>$2</em>")
      .replace(/(^|[^_\w])_([^_\n]+?)_(?!\w)/g, "$1<em>$2</em>")
      .replace(/~~([^~\n]+?)~~/g, "<s>$1</s>");
    return out.replace(/\u0000(\d+)\u0000/g, (all, index) => saved[Number(index)]);
  }

  // --- Block Markdown. Parses line by line so unfinished constructs still render during streaming.
  const LIST_ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
  const TABLE_RULE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;
  const splitRow = line => {
    const cells = line.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/);
    return cells.map(cell => cell.replace(/\\\|/g, "|").trim());
  };
  function table(header, aligns, rows) {
    const cell = (tag, text, index) => `<${tag}${aligns[index] ? ` style="text-align:${aligns[index]}"` : ""}>${inline(text)}</${tag}>`;
    const body = rows.map(row => `<tr>${header.map((_, index) => cell("td", row[index] ?? "", index)).join("")}</tr>`).join("");
    return `<div class="table-wrap"><table><thead><tr>${header.map((text, index) => cell("th", text, index)).join("")}</tr></thead>` +
      (body ? `<tbody>${body}</tbody>` : "") + "</table></div>";
  }
  function list(lines) {
    const root = {indent: -1, tag: "", items: []};
    const stack = [root];
    for (const raw of lines) {
      const match = LIST_ITEM.exec(raw);
      if (!match) {
        const last = stack.at(-1).items.at(-1);
        if (last && raw.trim()) last.text += " " + raw.trim();
        continue;
      }
      const indent = match[1].replace(/\t/g, "  ").length;
      const tag = /\d/.test(match[2]) ? "ol" : "ul";
      while (stack.length > 1 && indent < stack.at(-1).indent) stack.pop();
      let container = stack.at(-1);
      if (container === root || indent > container.indent || tag !== container.tag) {
        const parent = container.items.at(-1);
        const fresh = {indent, tag, items: [], start: tag === "ol" ? parseInt(match[2], 10) : 1};
        if (parent && container !== root) parent.children.push(fresh); else root.items.push(fresh);
        if (tag !== container.tag && container !== root && indent <= container.indent) stack.pop();
        stack.push(fresh);
        container = fresh;
      }
      container.items.push({text: match[3], children: []});
    }
    const renderList = node => {
      const start = node.tag === "ol" && node.start > 1 ? ` start="${node.start}"` : "";
      return `<${node.tag}${start}>${node.items.map(item => {
        const task = /^\[([ xX])\]\s+/.exec(item.text);
        const text = task ? `<span class="task ${task[1] === " " ? "" : "done"}"></span>${inline(item.text.slice(task[0].length))}` : inline(item.text);
        return `<li>${text}${item.children.map(renderList).join("")}</li>`;
      }).join("")}</${node.tag}>`;
    };
    return root.items.map(renderList).join("");
  }
  function render(text) {
    const lines = String(text).split("\n");
    let html = "", paragraph = [], i = 0, match;
    const flush = () => { if (paragraph.length) { html += `<p>${paragraph.map(inline).join("<br>")}</p>`; paragraph = []; } };
    while (i < lines.length) {
      const line = lines[i];
      if ((match = /^\s*(`{3,}|~{3,})\s*([\w+#.-]*)/.exec(line))) {
        flush();
        const fence = match[1][0], body = [];
        const closing = new RegExp(`^\\s*\\${fence}{3,}\\s*$`);
        i++;
        while (i < lines.length && !closing.test(lines[i])) body.push(lines[i++]);
        i++;
        html += codeBlock(body.join("\n"), match[2]);
        continue;
      }
      if (!line.trim()) { flush(); i++; continue; }
      if ((match = /^(#{1,6})\s+(.+?)\s*#*\s*$/.exec(line))) {
        flush();
        const tag = match[1].length <= 2 ? "h3" : "h4";
        html += `<${tag}>${inline(match[2])}</${tag}>`;
        i++; continue;
      }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); html += "<hr>"; i++; continue; }
      if (line.includes("|") && i + 1 < lines.length && TABLE_RULE.test(lines[i + 1])) {
        flush();
        const header = splitRow(line);
        const aligns = splitRow(lines[i + 1]).map(cell => /^:-+:$/.test(cell) ? "center" : /^-+:$/.test(cell) ? "right" : "");
        const rows = [];
        i += 2;
        while (i < lines.length && lines[i].trim() && lines[i].includes("|")) rows.push(splitRow(lines[i++]));
        html += table(header, aligns, rows);
        continue;
      }
      if (/^\s*>/.test(line)) {
        flush();
        const quote = [];
        while (i < lines.length && (match = /^\s*>\s?(.*)$/.exec(lines[i]))) { quote.push(match[1]); i++; }
        html += `<blockquote>${render(quote.join("\n"))}</blockquote>`;
        continue;
      }
      if (LIST_ITEM.test(line)) {
        flush();
        const items = [];
        while (i < lines.length) {
          const next = lines[i];
          if (LIST_ITEM.test(next) || /^\s+\S/.test(next)) { items.push(next); i++; continue; }
          if (!next.trim() && i + 1 < lines.length && (LIST_ITEM.test(lines[i + 1]) || /^\s+\S/.test(lines[i + 1]))) { i++; continue; }
          break;
        }
        html += list(items);
        continue;
      }
      paragraph.push(line);
      i++;
    }
    flush();
    return html;
  }
  return {render, inline, highlight, escape, codeBlock};
})();
