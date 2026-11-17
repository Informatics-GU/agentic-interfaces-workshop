import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    proxy: {
      '/agent': 'http://localhost:1537',
      '/demo-events': 'http://localhost:1537',
    },
  },
});
