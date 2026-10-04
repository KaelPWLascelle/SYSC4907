import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// The Python app serves the build from ../flicks/static (docs/adr/0004-react-vite-frontend.md).
// In development, run `flicks --dev` and `npm run dev`; Vite proxies API, poster and media requests to it.
const backend = 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../flicks/static',
    emptyOutDir: true,
    rollupOptions: { input: { main: 'index.html', couch: 'couch.html' } },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': backend, '/posters': backend, '/media': backend },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['src/test/setup.ts'],
    css: false,
  },
});
