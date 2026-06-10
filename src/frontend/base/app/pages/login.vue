<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { useSessionStore } from '~/stores/session'
import authService from '~/lib/api/authService'
import Branding from '../components/auth/Branding.vue'
import LoginForm from '../components/auth/LoginForm.vue'
import BackgroundEffects from '../components/BackgroundEffects.vue'

const session = useSessionStore()
const router = useRouter()
const config = useRuntimeConfig()
const isLoginLoading = ref(false)
const isMounted = ref(false)

const joinAppUrl = (baseUrl: unknown, path: string) => {
  const base = String(baseUrl || '').replace(/\/$/, '')
  return base ? `${base}${path}` : path
}

const redirectForRole = (role: string) => {
  const appKind = String(config.public.appKind || 'base')

  if (role === 'admin') {
    if (appKind === 'admin') {
      router.replace('/')
      return
    }
    window.location.href = joinAppUrl(config.public.adminAppUrl, '/')
    return
  }

  if (appKind === 'chat') {
    router.replace('/chat')
    return
  }
  window.location.href = joinAppUrl(config.public.chatAppUrl, '/chat')
}

onMounted(() => {
  isMounted.value = true
})

watch([() => session.user, () => session.isLoading, isMounted], () => {
  if (isMounted.value && !session.isLoading && session.user) {
    redirectForRole(session.user.role)
  }
}, { immediate: true })

const handleLogin = async (email: string, password: string) => {
  isLoginLoading.value = true
  try {
    await authService.login({ email, password })
    const profile = await authService.getMe()

    const sessionUser = {
      id: profile.id,
      name: profile.email.split('@')[0],
      email: profile.email,
      role: profile.role,
      department: profile.department || 'General',
      initials: profile.email.substring(0, 2).toUpperCase(),
    }

    session.signIn(sessionUser as any)
    redirectForRole(sessionUser.role)
  } catch (error: any) {
    console.error('Login error caught:', error)
    if (error.response?.status === 401) {
      console.log('401 Unauthorized detected')
      toast.error('Login failed. Please check your email or password!')
    } else {
      console.log('Generic error detected')
      toast.error('An error occurred, please try again later.')
    }
    isLoginLoading.value = false
  }
}

const containerVariants = {
  initial: { opacity: 0 },
  enter: {
    opacity: 1,
    transition: {
      staggerChildren: 100,
      delayChildren: 100,
    },
  },
}

const itemVariants = {
  initial: { opacity: 0, y: 15 },
  enter: {
    opacity: 1,
    y: 0,
    transition: {
      type: 'spring',
      stiffness: 70,
      damping: 14,
    },
  },
}

const cardVariants = {
  initial: { opacity: 0, y: 30 },
  enter: {
    opacity: 1,
    y: 0,
    transition: {
      type: 'spring',
      stiffness: 60,
      damping: 16,
    },
  },
}
</script>

<template>
  <div class="relative min-h-screen bg-[#f8fafc] flex items-center justify-center p-4 overflow-hidden transform-gpu" style="contain: strict;">
    <BackgroundEffects />

    <div
      class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-2xl h-[500px] rounded-full pointer-events-none transform-gpu"
      style="
        background: radial-gradient(circle, rgba(239, 68, 68, 0.05) 0%, transparent 70%);
        backface-visibility: hidden;
      "
    />

    <div
      v-if="isMounted && !session.isLoading"
      v-motion="containerVariants"
      class="relative z-10 w-full max-w-md transform-gpu"
      style="will-change: transform, opacity;"
    >
      <Branding :is-loading="isLoginLoading" />

      <div v-motion="cardVariants" class="transform-gpu" style="will-change: transform, opacity;">
        <LoginForm :is-loading="isLoginLoading" @login="handleLogin" />
      </div>

      <p
        v-motion="itemVariants"
        class="mt-8 text-center text-[10px] text-slate-500 font-bold uppercase tracking-widest transform-gpu"
        style="will-change: transform, opacity;"
      >
        © 2026 FEATUREMIND. SECURE AI SYSTEM.
      </p>
    </div>
  </div>
</template>
