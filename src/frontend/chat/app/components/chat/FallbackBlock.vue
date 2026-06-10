<script setup lang="ts">
import { AlertTriangle, Mail } from '@lucide/vue'
</script>

<template>
  <div class="rounded-xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
    <div class="flex items-start gap-3">
      <div class="flex h-8 w-8 items-center justify-center rounded-md bg-amber-100 text-amber-600">
        <AlertTriangle class="h-4 w-4" />
      </div>
      <div class="flex-1">
        <h3 class="text-[14px] font-semibold text-slate-900">
          No sufficiently relevant information was found
        </h3>
        <p class="mt-1 text-[13px] text-slate-600">
          We couldn't ground a confident answer in your indexed knowledge base
          for this query.
        </p>
        <div class="mt-4 grid gap-3 md:grid-cols-2">
          <div class="rounded-lg border border-slate-200 bg-white/60 p-3">
            <div class="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Try
            </div>
            <ul class="space-y-1 text-[12.5px] text-slate-600">
              <li>· Rephrase with more specific keywords</li>
              <li>· Mention the policy or document name</li>
              <li>· Narrow the scope (year, region, team)</li>
            </ul>
          </div>
          <div class="rounded-lg border border-slate-200 bg-white/60 p-3">
            <div class="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-400">
              Recommended contacts
            </div>
            <ul class="space-y-1 text-[12.5px] text-slate-600">
              <li class="flex items-center gap-1.5">
                <Mail class="h-3 w-3 text-slate-400" /> hr@featuremind.com
              </li>
              <li class="flex items-center gap-1.5">
                <Mail class="h-3 w-3 text-slate-400" /> it-support@featuremind.com
              </li>
              <li class="flex items-center gap-1.5">
                <Mail class="h-3 w-3 text-slate-400" /> finance@featuremind.com
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
