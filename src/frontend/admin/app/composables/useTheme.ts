export type Theme = 'light' | 'dark' | 'system'

export function useTheme() {
  const theme = useState<Theme>('theme', () => 'system')
  const route = useRoute()

  const setTheme = (newTheme: Theme) => {
    theme.value = newTheme
    if (import.meta.client) {
      localStorage.setItem('theme', newTheme)
      applyTheme()
    }
  }

  const applyTheme = () => {
    if (!import.meta.client) return

    // Login page luôn hiển thị light (giống chat) để brand/auth nhất quán.
    if (route.path === '/login') {
      document.documentElement.classList.remove('dark')
      return
    }

    const isDark =
      theme.value === 'dark' ||
      (theme.value === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)

    if (isDark) {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }

  const initTheme = () => {
    if (import.meta.client) {
      const savedTheme = localStorage.getItem('theme') as Theme | null
      if (savedTheme) {
        theme.value = savedTheme
      }
      applyTheme()

      // Theo dõi khi user đổi theme hệ thống (chỉ áp dụng khi đang ở chế độ 'system').
      window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
        if (theme.value === 'system') {
          applyTheme()
        }
      })
    }
  }

  return {
    theme,
    setTheme,
    initTheme,
    applyTheme,
  }
}
