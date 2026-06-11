export type Theme = 'light' | 'dark' | 'system'

export function useTheme() {
  const theme = useState<Theme>('theme', () => 'system')

  const setTheme = (newTheme: Theme) => {
    theme.value = newTheme
    if (process.client) {
      localStorage.setItem('theme', newTheme)
      applyTheme()
    }
  }

  const applyTheme = () => {
    if (!process.client) return

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
    if (process.client) {
      const savedTheme = localStorage.getItem('theme') as Theme | null
      if (savedTheme) {
        theme.value = savedTheme
      }
      applyTheme()

      // Watch for system theme changes
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
    applyTheme
  }
}
