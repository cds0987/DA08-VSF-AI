<script setup lang="ts">
import { ref, computed } from 'vue'
import { cn } from '~/lib/utils'

interface Props {
  isLoading: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'login', email: string, password: string): void
}>()

const email = ref('')
const password = ref('')
const emailTouched = ref(false)
const passwordTouched = ref(false)
const isEmailFocused = ref(false)
const isPasswordFocused = ref(false)

const emailEmpty = computed(() => emailTouched.value && email.value.trim() === '')
const passwordEmpty = computed(() => passwordTouched.value && password.value.trim() === '')
const emailInvalidFormat = computed(() => emailTouched.value && email.value.trim() !== '' && !email.value.includes('@'))

const handleSubmit = () => {
  emailTouched.value = true
  passwordTouched.value = true
  
  if (!email.value.trim() || emailInvalidFormat.value || !password.value.trim()) return
  emit('login', email.value, password.value)
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

const textPulseVariants = {
  initial: { opacity: 0.4 },
  enter: {
    opacity: [0.4, 1, 0.4],
    transition: {
      duration: 5000,
      repeat: Infinity,
      ease: 'easeInOut',
    },
  },
}
</script>

<template>
  <div
    v-motion="itemVariants"
    class="relative rounded-2xl border border-slate-200 bg-white/80 backdrop-blur-md p-8 shadow-2xl shadow-slate-200/50 transform-gpu"
    style="contain: layout paint; backface-visibility: hidden;"
  >
    <div
      v-motion="textPulseVariants"
      class="absolute top-0 left-1/4 right-1/4 h-[1px] bg-red-500/20 z-20 pointer-events-none"
      style="transform: translateZ(0);"
    />
    <div class="absolute inset-0 rounded-2xl bg-gradient-to-br from-white/50 to-transparent pointer-events-none" />

    <h2
      v-motion="itemVariants"
      class="relative z-10 mb-8 text-xl font-bold text-slate-900 tracking-tight"
    >
      Login
    </h2>

    <form novalidate @submit.prevent="handleSubmit" class="space-y-5 relative z-10">
      <div v-motion="itemVariants" class="relative group">
        <label class="block text-xs font-medium text-slate-600 uppercase tracking-wider mb-2">
          Email
        </label>
        <div class="relative">
          <input
            v-model="email"
            type="email"
            @focus="() => { emailTouched = true; isEmailFocused = true }"
            @blur="isEmailFocused = false"
            placeholder="admin@example.com"
            :class="cn(
              'w-full px-4 py-3 rounded-lg border bg-slate-100/50 text-sm text-slate-900 placeholder-slate-400 outline-none transition-all duration-200 relative z-10',
              'focus:outline-none focus:ring-4 focus-visible:outline-none',
              (emailEmpty || emailInvalidFormat)
                ? 'border-red-500 ring-4 ring-red-500/10' 
                : (isEmailFocused 
                    ? 'border-blue-500 ring-blue-500/10' 
                    : (email.length > 0 ? 'border-blue-500/30' : 'border-slate-200')),
            )"
          />
          <p v-if="emailInvalidFormat" class="text-red-500 text-xs mt-1 transition-all">
            Invalid email format (missing @)
          </p>
          <p v-else-if="emailEmpty" class="text-red-500 text-xs mt-1 transition-all">
            Email is required
          </p>
        </div>
      </div>

      <div v-motion="itemVariants" class="relative group">
        <label class="block text-xs font-medium text-slate-600 uppercase tracking-wider mb-2">
          Password
        </label>
        <div class="relative">
          <input
            v-model="password"
            type="password"
            @focus="() => { passwordTouched = true; isPasswordFocused = true }"
            @blur="isPasswordFocused = false"
            placeholder="password123"
            :class="cn(
              'w-full px-4 py-3 rounded-lg border bg-slate-100/50 text-sm text-slate-900 placeholder-slate-400 outline-none transition-all duration-200 relative z-10',
              'focus:outline-none focus:ring-4 focus-visible:outline-none',
              passwordEmpty 
                ? 'border-red-500 ring-4 ring-red-500/10' 
                : (isPasswordFocused 
                    ? 'border-blue-500 ring-blue-500/10' 
                    : (password.length > 0 ? 'border-blue-500/30' : 'border-slate-200')),
            )"
          />
          <p v-if="passwordEmpty" class="text-red-500 text-xs mt-1 transition-all">
            Password is required
          </p>
        </div>
      </div>

      <button
        type="submit"
        v-motion="itemVariants"
        :disabled="isLoading"
        class="relative w-full py-3 px-4 mt-2 rounded-lg font-bold text-sm text-white bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-500 hover:to-cyan-500 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-300 shadow-lg shadow-blue-500/25 transform-gpu"
        style="will-change: transform;"
      >
        <span :class="{ 'opacity-70': isLoading }">
          {{ isLoading ? 'Signing in...' : 'Login' }}
        </span>
      </button>
    </form>

    <div
      v-if="isLoading"
      v-motion
      :initial="{ scaleX: 0 }"
      :enter="{ scaleX: 1, transition: { duration: 1500 } }"
      class="absolute bottom-0 left-0 h-1 bg-gradient-to-r from-blue-400 to-cyan-400 rounded-b-lg transform-gpu w-full origin-left"
      style="will-change: transform;"
    />
  </div>
</template>

