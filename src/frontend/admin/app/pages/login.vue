<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { useSessionStore } from '~/stores/session'
import authService from '~/lib/api/authService'
import { ShieldAlert } from '@lucide/vue'
import Branding from '../components/auth/Branding.vue'
import LoginForm from '../components/auth/LoginForm.vue'
import BackgroundEffects from '../components/BackgroundEffects.vue'
import { Alert, AlertDescription, AlertTitle } from '~/components/ui/alert'

const session = useSessionStore()
const router = useRouter()
const route = useRoute()
const isLoginLoading = ref(false)
const isMounted = ref(false)
// Capture state early to avoid losing it during re-renders/redirects
const showForbiddenAlert = ref(route.query.error === 'forbidden')

const redirectForSession = () => {
  if (!session.user) return
  if (session.user.role !== 'admin') {
    // Clear invalid session without hard reload to preserve URL query/state
    session.signOut()
    authService.logout(false)
    return
  }
  router.replace('/')
}

onMounted(() => {
  isMounted.value = true
  if (showForbiddenAlert.value) {
    toast.error('Access Denied: Your account does not have admin privileges.')
    // Clear query parameter via soft navigation
    router.replace({ query: {} })
  }
})

watch([() => session.user, () => session.isLoading, isMounted], () => {
  if (isMounted.value && !session.isLoading) {
    redirectForSession()
  }
}, { immediate: true })

const handleLogin = async (email: string, password: string) => {
  isLoginLoading.value = true
  try {
    await authService.login({ email, password })
    const profile = await authService.getMe()
    console.log('Login successful, profile retrieved:', profile)

    if (!profile || !profile.email) {
      throw new Error('Profile data is incomplete: email is missing.')
    }

    if (profile.role !== 'admin') {
      toast.error('Forbidden: Your account does not have admin privileges.')
      authService.logout()
      return
    }

    session.signIn({
      id: profile.id,
      name: profile.email.split('@')[0],
      email: profile.email,
      role: profile.role,
      department: profile.department || 'General',
      initials: profile.email.substring(0, 2).toUpperCase(),
    })
    router.replace('/')
  } catch (error: any) {
    console.error('Login Process Error:', error)
    const status = error.response?.status
    if (status === 401) {
      toast.error('Login failed. Please check your email or password!')
    } else if (status === 423) {
      toast.error('Account locked due to too many failed attempts. Please try again in 15 minutes.')
    } else {
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
        <LoginForm :is-loading="isLoginLoading" @login="handleLogin">
          <template v-if="showForbiddenAlert" #alert>
            <Alert variant="destructive" class="border-red-200 bg-red-50/50">
              <ShieldAlert class="h-4 w-4 text-red-600" />
              <AlertTitle class="font-bold text-red-800">403 - Access Denied</AlertTitle>
              <AlertDescription class="text-red-700">
                Your account does not have permission to access the Admin Application. Please log in with an authorized administrator account.
              </AlertDescription>
            </Alert>
          </template>
        </LoginForm>
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
