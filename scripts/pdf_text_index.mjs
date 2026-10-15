// Trusted local adapter; no document paths or text are written to diagnostics.
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { getDocument, GlobalWorkerOptions, version } from '../apps/web/node_modules/pdfjs-dist/legacy/build/pdf.mjs';

GlobalWorkerOptions.workerSrc = new URL('../apps/web/node_modules/pdfjs-dist/legacy/build/pdf.worker.mjs', import.meta.url).href;
try {
  const [file, rawPages] = process.argv.slice(2);
  const pages = JSON.parse(rawPages);
  if (version !== '6.4.299' || !Array.isArray(pages) || pages.length < 1 || pages.length > 64 ||
    pages.some(page => !Number.isSafeInteger(page) || page < 1) || new Set(pages).size !== pages.length) throw new Error();
  const bytes = await readFile(file);
  if (bytes.length > 100 * 1024 * 1024) throw new Error();
  const base = fileURLToPath(new URL('../apps/web/node_modules/pdfjs-dist/', import.meta.url));
  const loading = getDocument({ data: new Uint8Array(bytes), enableXfa: false, useSystemFonts: false,
    cMapUrl: base + 'cmaps/', cMapPacked: true, standardFontDataUrl: base + 'standard_fonts/', wasmUrl: base + 'wasm/', verbosity: 0 });
  const pdf = await loading.promise;
  const pageCount = pdf.numPages;
  const result = [];
  let characters = 0, itemCount = 0;
  for (const number of pages) {
    if (number > pdf.numPages) throw new Error();
    const page = await pdf.getPage(number);
    const content = await page.getTextContent({ includeMarkedContent: false, disableNormalization: false });
    const items = content.items.map((item, index) => {
      if (typeof item.str !== 'string') throw new Error();
      characters += item.str.length; itemCount++;
      if (characters > 2000000 || itemCount > 100000) throw new Error();
      return { index, str: item.str, has_eol: Boolean(item.hasEOL) };
    });
    result.push({ page: number, items });
  }
  await loading.destroy();
  process.stdout.write(JSON.stringify({ schema_version: 'selection-pdf-index/1.0', pdfjs_version: version,
    pdf_sha256: createHash('sha256').update(bytes).digest('hex'), page_count: pageCount, pages: result }));
} catch {
  process.stderr.write('PDF selection index could not be verified.\n');
  process.exitCode = 1;
}
