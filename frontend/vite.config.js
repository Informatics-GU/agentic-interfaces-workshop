import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    host: true,                      // listen on 0.0.0.0
    port: 5173,
    strictPort: true,                // fail instead of silently moving ports
    allowedHosts: ['.adcproxy.io'],  // sandbox proxy hostnames
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
