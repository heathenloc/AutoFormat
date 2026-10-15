import { getDocument, GlobalWorkerOptions, TextLayer, type PDFDocumentProxy, type PDFDocumentLoadingTask, type RenderTask } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.mjs?url';
import type { TextItem } from 'pdfjs-dist/types/src/display/api';
import { readSelection, type TextEntry } from './selection';
import type { SelectionHint } from './contracts';

GlobalWorkerOptions.workerSrc = workerUrl;

export class PdfViewer {
  private loading: PDFDocumentLoadingTask | null = null;
  private document: PDFDocumentProxy | null = null;
  private renderTask: RenderTask | null = null;
  private textLayer: TextLayer | null = null;
  private entries: TextEntry[] = [];
  private renderEpoch = 0;
  private page = 1;
  constructor(private readonly container: HTMLElement) {}

  async open(bytes: Uint8Array, expectedPages: number): Promise<void> {
    await this.dispose();
    const loading = getDocument({
      data: bytes, enableXfa: false, useSystemFonts: false,
      cMapUrl: '/assets/pdfjs/cmaps/', cMapPacked: true,
      standardFontDataUrl: '/assets/pdfjs/standard_fonts/', wasmUrl: '/assets/pdfjs/wasm/',
    });
    this.loading = loading;
    const pdf = await loading.promise;
    if (this.loading !== loading) return;
    if (pdf.numPages !== expectedPages) { await this.dispose(); throw new Error('PDF page count mismatch'); }
    this.document = pdf;
  }
  async render(page: number, scale: number | 'fit'): Promise<number | null> {
    const pdf = this.document;
    if (!pdf) return null;
    const epoch = ++this.renderEpoch;
    this.renderTask?.cancel(); this.textLayer?.cancel(); this.entries = [];
    const pdfPage = await pdf.getPage(page);
    if (epoch !== this.renderEpoch) return null;
    const base = pdfPage.getViewport({ scale: 1 });
    const actualScale = scale === 'fit' ? Math.min(2, Math.max(0.4, (this.container.clientWidth - 64) / base.width)) : scale;
    const viewport = pdfPage.getViewport({ scale: actualScale });
    const paper = document.createElement('div');
    paper.className = 'pdf-page'; paper.dataset.page = String(page);
    paper.style.width = `${viewport.width}px`; paper.style.height = `${viewport.height}px`;
    paper.style.setProperty('--scale-factor', String(actualScale));
    paper.style.setProperty('--total-scale-factor', String(actualScale));
    const canvas = document.createElement('canvas');
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(viewport.width * ratio); canvas.height = Math.floor(viewport.height * ratio);
    canvas.style.width = `${viewport.width}px`; canvas.style.height = `${viewport.height}px`;
    canvas.setAttribute('aria-label', `论文第 ${page} 页`);
    const layer = document.createElement('div'); layer.className = 'textLayer';
    paper.append(canvas, layer); this.container.replaceChildren(paper);
    const renderTask = pdfPage.render({ canvas, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] });
    this.renderTask = renderTask;
    // Cancellation may happen while text extraction is still pending.
    const renderPromise = renderTask.promise;
    void renderPromise.catch(() => undefined);
    const content = await pdfPage.getTextContent({ includeMarkedContent: false, disableNormalization: false });
    if (epoch !== this.renderEpoch) return null;
    const textLayer = new TextLayer({ textContentSource: content, container: layer, viewport });
    this.textLayer = textLayer;
    try { await Promise.all([renderPromise, textLayer.render()]); }
    catch (error) { if (epoch !== this.renderEpoch) return null; throw error; }
    if (epoch !== this.renderEpoch) return null;
    const items = content.items.map((item, index) => ({ item, index })).filter((entry): entry is { item: TextItem; index: number } => 'str' in entry.item);
    this.entries = textLayer.textDivs.map((element, i) => ({ element, index: items[i].index, text: items[i].item.str, hasEOL: items[i].item.hasEOL }));
    for (const entry of this.entries) entry.element.dataset.pdfItem = String(entry.index);
    this.page = page;
    return actualScale;
  }
  selection(): SelectionHint | null {
    const layer = this.container.querySelector<HTMLElement>('.textLayer');
    return layer ? readSelection(layer, this.entries, this.page) : null;
  }
  async dispose() {
    ++this.renderEpoch;
    this.renderTask?.cancel(); this.textLayer?.cancel(); this.renderTask = null; this.textLayer = null;
    this.document = null; this.entries = []; this.container.replaceChildren();
    const loading = this.loading; this.loading = null;
    if (loading) await loading.destroy();
  }
}
