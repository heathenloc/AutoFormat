import type { SelectionHint } from './contracts';

export interface TextEntry { element: HTMLElement; index: number; text: string; hasEOL: boolean }

export function readSelection(layer: HTMLElement, entries: TextEntry[], page: number): SelectionHint | null {
  const selection = window.getSelection();
  if (!selection || selection.rangeCount !== 1 || selection.isCollapsed) return null;
  const range = selection.getRangeAt(0);
  // A selection extending into toolbars or the feedback panel is not a PDF hint.
  if (!layer.contains(range.startContainer) || !layer.contains(range.endContainer)) return null;
  const hits: { entry: TextEntry; start: number; end: number }[] = [];
  for (const entry of entries) {
    if (!entry.text || !layer.contains(entry.element) || !range.intersectsNode(entry.element)) continue;
    const contents = document.createRange();
    contents.selectNodeContents(entry.element);
    const intersection = contents.cloneRange();
    if (entry.element.contains(range.startContainer)) intersection.setStart(range.startContainer, range.startOffset);
    else if (range.compareBoundaryPoints(Range.START_TO_START, contents) > 0) continue;
    if (entry.element.contains(range.endContainer)) intersection.setEnd(range.endContainer, range.endOffset);
    else if (range.compareBoundaryPoints(Range.END_TO_END, contents) < 0) continue;
    const prefix = contents.cloneRange();
    prefix.setEnd(intersection.startContainer, intersection.startOffset);
    const start = prefix.toString().length;
    const end = start + intersection.toString().length;
    if (end > start) hits.push({ entry, start, end });
  }
  if (!hits.length) return null;
  const first = hits[0], last = hits[hits.length - 1];
  // Reconstruct from item strings rather than browser-added visual whitespace.
  const selected = entries.filter(entry => entry.index >= first.entry.index && entry.index <= last.entry.index)
    .map(entry => entry.text.slice(entry === first.entry ? first.start : 0, entry === last.entry ? last.end : undefined) +
      (entry.index < last.entry.index && entry.hasEOL ? '\n' : '')).join('');
  if (!selected.trim() || selected.length > 4096) return null;
  const before = entries.filter(entry => entry.index < first.entry.index).map(entry => entry.text).join('') + first.entry.text.slice(0, first.start);
  const after = last.entry.text.slice(last.end) + entries.filter(entry => entry.index > last.entry.index).map(entry => entry.text).join('');
  // The contiguous PDF item range also contains empty EOL items. It remains a
  // hint; a server-side resolver must verify it before creating a DOCX anchor.
  return {
    selected_text: selected, context_before: safeContext(before, true), context_after: safeContext(after, false),
    spans: [{ page, start_item: first.entry.index, start_offset_utf16: first.start,
      end_item: last.entry.index, end_offset_utf16: last.end }],
  };
}

function safeContext(value: string, suffix: boolean): string {
  let result = suffix ? value.slice(-256) : value.slice(0, 256);
  // A context limit must not create half of a UTF-16 surrogate pair.
  if (/^[\uDC00-\uDFFF]/.test(result)) result = result.slice(1);
  if (/[\uD800-\uDBFF]$/.test(result)) result = result.slice(0, -1);
  return result;
}
