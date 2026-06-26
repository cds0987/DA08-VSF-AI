<script setup lang="ts">
import { AlertTriangle, Mail } from '@lucide/vue'
</script>

<template>
  <div class="rounded-xl border border-amber-200 dark:border-amber-500/20 bg-amber-50 dark:bg-amber-500/5 p-5">
    <div class="flex items-start gap-3">
      <div class="flex h-8 w-8 items-center justify-center rounded-md bg-amber-100 dark:bg-amber-500/10 text-amber-600 dark:text-amber-400">
        <AlertTriangle class="h-4 w-4" />
      </div>
      <div class="flex-1">
        <h3 class="text-[14px] font-semibold text-slate-900 dark:text-foreground">
          No sufficiently relevant information was found
        </h3>
        <p class="mt-1 text-[13px] text-slate-600 dark:text-muted-foreground">
          We couldn't ground a confident answer in your indexed knowledge base
          for this query.
        </p>
        <div class="mt-4 grid gap-3 md:grid-cols-2">
          <div class="rounded-lg border border-slate-200 dark:border-border bg-white/60 dark:bg-card p-3">
            <div class="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-muted-foreground">
              Try
            </div>
            <ul class="space-y-1 text-[12.5px] text-slate-600 dark:text-foreground/80">
              <li>· Rephrase with more specific keywords</li>
              <li>· Mention the policy or document name</li>
              <li>· Narrow the scope (year, region, team)</li>
            </ul>
          </div>
          <div class="rounded-lg border border-slate-200 dark:border-border bg-white/60 dark:bg-card p-3">
            <div class="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-muted-foreground">
              Recommended contacts
            </div>
            <ul class="space-y-1 text-[12.5px] text-slate-600 dark:text-foreground/80">
              <li class="flex items-center gap-1.5">
                <Mail class="h-3 w-3 text-slate-500 dark:text-muted-foreground" /> hr@featuremind.com
              </li>
              <li class="flex items-center gap-1.5">
                <Mail class="h-3 w-3 text-slate-500 dark:text-muted-foreground" /> it-support@featuremind.com
              </li>
              <li class="flex items-center gap-1.5">
                <Mail class="h-3 w-3 text-slate-500 dark:text-muted-foreground" /> finance@featuremind.com
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
