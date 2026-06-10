import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'

const baseAppPath = fileURLToPath(new URL('./app', import.meta.url))

export default defineNuxtConfig({
  compatibilityDate: '2024-11-01',
  devtools: { enabled: true },
  modules: [
    '@pinia/nuxt',
    '@vueuse/nuxt',
    '@vueuse/motion/nuxt',
  ],
  components: [
    {
      path: `${baseAppPath}/components/ui`,
      extensions: ['.vue'],
      pathPrefix: false,
    },
    `${baseAppPath}/components`,
  ],
  css: [`${baseAppPath}/assets/css/tailwind.css`],
  runtimeConfig: {
    public: {
      apiGatewayUrl: process.env.NUXT_PUBLIC_API_GATEWAY_URL || 'http://localhost',
      apiBaseUrl: process.env.NUXT_PUBLIC_API_BASE_URL || 'http://localhost:8000',
      appKind: process.env.NUXT_PUBLIC_APP_KIND || 'base',
      adminAppUrl: process.env.NUXT_PUBLIC_ADMIN_APP_URL || 'http://localhost:3001',
      chatAppUrl: process.env.NUXT_PUBLIC_CHAT_APP_URL || 'http://localhost:3000',
    },
  },
  vite: {
    resolve: {
      dedupe: [
        'vue',
        '@vue/runtime-core',
        '@vue/server-renderer',
        '@vueuse/core',
        'pinia',
        'reka-ui',
        'vue-sonner',
      ],
    },
    plugins: [
      tailwindcss(),
    ],
  },
  future: {
    compatibilityVersion: 4,
  },
})
