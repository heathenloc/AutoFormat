import { defineConfig } from 'vite';
import { cpSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

export default defineConfig({
  build: { target: 'es2022' },
  plugins: [{
    name: 'local-pdf-resources',
    closeBundle() {
      const destination = resolve('dist/assets/pdfjs');
      mkdirSync(destination, { recursive: true });
      for (const directory of ['cmaps', 'standard_fonts', 'wasm']) {
        cpSync(resolve('node_modules/pdfjs-dist', directory), resolve(destination, directory), { recursive: true });
      }
    },
  }],
});
