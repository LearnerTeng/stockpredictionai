import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '127.0.0.1'
  },
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        monitor: resolve(__dirname, 'monitor.html'),
        imageLab: resolve(__dirname, 'image-lab.html'),
        insights: resolve(__dirname, 'insights.html'),
      },
    },
  }
})
