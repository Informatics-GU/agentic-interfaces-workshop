import { defineConfig } from 'vite';

const backendUrl = process.env.STUDY_PLANNER_BACKEND_URL;

export default defineConfig({
  server: {
    port: 5173,
    strictPort: true,
    proxy: backendUrl ? {
      '/agent': backendUrl,
      '/demo-events': backendUrl,
      '/health': backendUrl,
      '/catalog': backendUrl,
    } : undefined,
  },
});
