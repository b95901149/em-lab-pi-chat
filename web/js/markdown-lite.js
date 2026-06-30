/** Minimal markdown-ish renderer for assistant messages. */

export function renderMarkdown(text) {
  const escaped = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  let html = escaped
    .replace(/^## (.+)$/gm, '<div class="md-h2">$1</div>')
    .replace(/^### (.+)$/gm, '<div class="md-h3">$1</div>')
    .replace(/^- \[ \] (.+)$/gm, "<li>$1</li>")
    .replace(/^- \[x\] (.+)$/gim, "<li><s>$1</s></li>")
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

  html = html.replace(/(<li>.*<\/li>\n?)+/g, (m) => `<ul>${m}</ul>`);
  html = html.replace(/\n---\n/g, "<hr/>");
  html = html.replace(/\n/g, "<br/>");
  return html;
}
