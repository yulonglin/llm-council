import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/**
 * Fix tables where an LLM puts all rows on a single line, e.g.:
 * | H1 | H2 | |---|---| | D1 | D2 | | D3 | D4 |
 * Inserts newlines at row boundaries so ReactMarkdown can parse them.
 */
function fixInlineTables(text) {
  if (!text) return '';
  return text.split('\n').map(line => {
    // Only target lines containing a table separator (|---|) with content around it
    const sepMatch = line.match(/(\|[\s]*[-:]+[\s]*(?:\|[\s]*[-:]+[\s]*)*\|)/);
    if (!sepMatch) return line;

    const sepStart = line.indexOf(sepMatch[0]);
    const sepEnd = sepStart + sepMatch[0].length;
    const before = line.substring(0, sepStart).trim();
    const after = line.substring(sepEnd).trim();

    // If separator is already on its own line, nothing to fix
    if (!before && !after) return line;

    // Insert newlines around the separator and between subsequent rows.
    // Row boundaries look like "| |" (end-of-row pipe, space, start-of-row pipe).
    // Within a row, pipes have content between them ("text | text"), so "| |" is unique to boundaries.
    const rows = after ? after.replace(/\|\s+\|/g, '|\n|') : '';
    return [before, sepMatch[0], rows].filter(Boolean).join('\n');
  }).join('\n');
}

export default function Markdown({ children, ...props }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} {...props}>
      {fixInlineTables(children)}
    </ReactMarkdown>
  );
}
