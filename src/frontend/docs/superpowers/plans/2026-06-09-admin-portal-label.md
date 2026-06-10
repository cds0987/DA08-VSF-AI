# Admin Portal Label Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a secondary label "ADMIN PORTAL" below the "FeatureMind" brand name on the login page to clearly identify the application context.

**Architecture:** Update the `Branding.vue` component to include the label with specific styling (mono font, wide tracking) and ensure it participates in the existing motion animations.

**Tech Stack:** Vue 3, Nuxt, Tailwind CSS, Motion (v-motion).

---

### Task 1: Verify Branding on Login Page (Failing Test)

**Files:**
- Create: `admin/tests/e2e/login-branding.spec.ts`

- [ ] **Step 1: Write the failing E2E test**

Create `admin/tests/e2e/login-branding.spec.ts`:
```typescript
import { expect, test } from '@playwright/test'

test.describe('Login Branding', () => {
  test('should display "ADMIN PORTAL" label below brand name', async ({ page }) => {
    await page.goto('http://localhost:3001/login')
    
    // Check for FeatureMind branding
    await expect(page.getByRole('heading', { name: 'FeatureMind' }).first()).toBeVisible()
    
    // Check for Admin portal label
    const adminPortalLabel = page.getByText('ADMIN PORTAL')
    await expect(adminPortalLabel).toBeVisible()
    
    // Check styling (optional but good for verification)
    await expect(adminPortalLabel).toHaveClass(/font-mono/)
    await expect(adminPortalLabel).toHaveClass(/uppercase/)
    await expect(adminPortalLabel).toHaveClass(/tracking-\[0.2em\]/)
  })
})
```

- [ ] **Step 2: Run the test and verify failure**

Run: `npx playwright test admin/tests/e2e/login-branding.spec.ts`
Expected: FAIL (label not found)

- [ ] **Step 3: Commit the test**

```bash
git add admin/tests/e2e/login-branding.spec.ts
git commit -m "test: add E2E test for login branding label"
```

### Task 2: Implement "ADMIN PORTAL" Label in Branding Component

**Files:**
- Modify: `admin/app/components/auth/Branding.vue`

- [ ] **Step 1: Add the label to Branding.vue**

Update `admin/app/components/auth/Branding.vue`:
```vue
<<<<
      <div class="relative">
        <h1
          class="text-4xl sm:text-5xl font-extrabold tracking-tight text-[#0f172a] relative z-10"
        >
          FeatureMind
        </h1>

        <!-- Optimized Text Pulse -->
        <h1
          v-motion="textPulseVariants"
          class="absolute inset-0 text-4xl sm:text-5xl font-extrabold tracking-tight z-20 pointer-events-none transform-gpu"
          style="
            background: linear-gradient(to bottom, #E11D48 0%, transparent 70%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            will-change: opacity;
          "
        >
          FeatureMind
        </h1>
      </div>
====
      <div class="relative">
        <h1
          class="text-4xl sm:text-5xl font-extrabold tracking-tight text-[#0f172a] relative z-10"
        >
          FeatureMind
        </h1>

        <!-- Optimized Text Pulse -->
        <h1
          v-motion="textPulseVariants"
          class="absolute inset-0 text-4xl sm:text-5xl font-extrabold tracking-tight z-20 pointer-events-none transform-gpu"
          style="
            background: linear-gradient(to bottom, #E11D48 0%, transparent 70%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            will-change: opacity;
          "
        >
          FeatureMind
        </h1>

        <p
          v-motion="itemVariants"
          class="text-[10px] font-mono font-bold uppercase tracking-[0.2em] text-slate-500 mt-1 relative z-10"
        >
          Admin portal
        </p>
      </div>
>>>>
```

- [ ] **Step 2: Run the E2E test and verify success**

Run: `npx playwright test admin/tests/e2e/login-branding.spec.ts`
Expected: PASS

- [ ] **Step 3: Commit the implementation**

```bash
git add admin/app/components/auth/Branding.vue
git commit -m "feat: add ADMIN PORTAL label to login branding"
```
