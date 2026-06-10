# Design Spec: Admin Portal Label

Adding a subtitle label "ADMIN PORTAL" to the branding section of the Admin Login page to clearly distinguish it from other portals (like the Chat portal).

## Goal
- Clearly identify the current application as the "Admin Portal" during the login process.
- Maintain the premium, technical, and secure aesthetic of the existing FeatureMind branding.

## Design (Option A: Mono Caps)
The label will be styled to match the technical/secure vibe of the system, using typography that mirrors the "SECURE AI SYSTEM" footer.

### Visual Specification
- **Text Content:** `ADMIN PORTAL`
- **Component:** `admin/app/components/auth/Branding.vue`
- **Styling (Tailwind):**
  - Font: `font-mono`
  - Size: `text-[10px]`
  - Weight: `font-bold`
  - Case: `uppercase`
  - Tracking: `tracking-[0.2em]`
  - Color: `text-slate-500`
  - Margin: `mt-1` (top margin to space it from the main "FeatureMind" heading)

## Implementation Details
The label will be placed inside the branding block, specifically after the `h1` headings in `Branding.vue`. It should be wrapped in a `motion` div (using `itemVariants`) to ensure it animates in with the rest of the branding elements.

### Proposed Code Change
In `admin/app/components/auth/Branding.vue`:
```vue
<!-- ... after the h1 tags ... -->
<p
  v-motion="itemVariants"
  class="text-[10px] font-mono font-bold uppercase tracking-[0.2em] text-slate-500 mt-1 relative z-10"
>
  Admin portal
</p>
```

## Success Criteria
- The "ADMIN PORTAL" text is visible below "FeatureMind" on the login page.
- The text animates in smoothly along with the brand title.
- The styling is consistent with the established design system (mono font, wide tracking).
