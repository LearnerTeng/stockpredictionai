import { resolve } from 'node:path'
import { defineConfig } from 'vite'

export default defineConfig({
  server: {
    port: 5173,
    host: true
  },
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        imageLab: resolve(__dirname, 'image-lab.html'),
        insights: resolve(__dirname, 'insights.html'),
      },
    },
  }
})
