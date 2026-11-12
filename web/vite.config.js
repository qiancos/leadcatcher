import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发态：前端 5173，API 代理到后端 8000
// 生产态：构建产物直接落到 server/app/static，由 FastAPI 单服务托管（Render 一条命令部署）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true }
    }
  },
  build: {
    outDir: '../server/app/static',
    emptyOutDir: true,
    rollupOptions: {
      // 拆包：Element Plus 和 ECharts 各自成块，首屏只下首屏要的
      output: {
        manualChunks: {
          vue: ['vue', 'vue-router'],
          element: ['element-plus'],
          charts: ['echarts']
        }
      }
    }
  }
})
