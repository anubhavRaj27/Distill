/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react()],

  server: {
    port: 5173,
    /*
     * The interface talks to the API through a same-origin path in development, which is
     * how it behaves in production too: FastAPI serves the built assets itself, so there
     * is no cross-origin surface at all (implementation.md section 10). Proxying here
     * means the deployed configuration is the one being developed against, rather than a
     * CORS setup that only exists on a laptop.
     *
     * `ws: false` and no buffering: the event stream is Server-Sent Events over plain
     * HTTP, and Vite's proxy passes it through unbuffered as long as it is not treated as
     * a websocket upgrade.
     */
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: false,
      },
      '/healthz': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },

  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    /*
     * The client uses a relative API base so that development and production are the same
     * same-origin configuration. A browser resolves that against the page; jsdom's fetch
     * does not, and rejects a relative URL outright. Tests therefore get an explicit
     * origin — it changes nothing about what is being asserted, since every assertion is
     * on the path.
     */
    env: { VITE_API_URL: 'http://distill.test' },
  },
});
