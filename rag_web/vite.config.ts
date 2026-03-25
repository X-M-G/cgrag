import { fileURLToPath, URL } from 'node:url'

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // 加载项目根目录下的 .env 文件
  const env = loadEnv(mode, '../')

  return {
    plugins: [
      vue(),
      vueDevTools(),
    ],
    envDir: '../', // 指定环境变量所在目录为根目录
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url))
      },
    },
    server: {
      port: 3000,   // 使用3000端口
      strictPort: false,
      host: true,   // 监听所有网络接口

      // ======== 🚀 动态配置代理以解决 CORS 问题 ========
      proxy: {
        // 匹配所有以 '/api' 开头的请求路径
        '/api': {
          // 将请求转发的目标地址设置为环境变量中的服务器地址
        //  'http://127.0.0.1:8000'
         // target: `http://${env.VITE_PUBLIC_IP || '127.0.0.1'}:${env.VITE_API_PORT || '8000'}`,
         target: 'http://127.0.0.1:8000',
          // 允许跨域
          changeOrigin: true,
        }
      }
      // ===================================================
    },
  }
})