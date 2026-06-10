import { fileURLToPath } from 'node:url'
import tailwindcss from '@tailwindcss/vite'

const appPath = fileURLToPath(new URL('./app', import.meta.url))

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
      path: `${appPath}/components/ui`,
      extensions: ['.vue'],
      pathPrefix: false,
    },
    `${appPath}/components`,
  ],
  css: [`${appPath}/assets/css/tailwind.css`],
  runtimeConfig: {
    public: {
      appKind: 'chat',
      apiGatewayUrl: '', // NUXT_PUBLIC_API_GATEWAY_URL
      gatewayBasicAuth: '', // NUXT_PUBLIC_GATEWAY_BASIC_AUTH
      userServicePath: '', // NUXT_PUBLIC_USER_SERVICE_PATH
      documentServicePath: '', // NUXT_PUBLIC_DOCUMENT_SERVICE_PATH
      queryServicePath: '', // NUXT_PUBLIC_QUERY_SERVICE_PATH
      hrServicePath: '', // NUXT_PUBLIC_HR_SERVICE_PATH
      mcpServicePath: '', // NUXT_PUBLIC_MCP_SERVICE_PATH
      adminAppUrl: '', // NUXT_PUBLIC_ADMIN_APP_URL
      chatAppUrl: '', // NUXT_PUBLIC_CHAT_APP_URL
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
  devServer: {
    port: 3000,
  },
})
