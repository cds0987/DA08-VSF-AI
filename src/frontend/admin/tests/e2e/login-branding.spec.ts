import { expect, test } from '@playwright/test'

test.describe('Login Branding', () => {
  test('should display "ADMIN PORTAL" label below brand name', async ({ page }) => {
    await page.goto('/login')
    
    // Check for FeatureMind branding
    await expect(page.getByRole('heading', { name: 'FeatureMind' }).first()).toBeVisible()
    
    // Check for Admin portal label
    const adminPortalLabel = page.getByText(/admin portal/i)
    await expect(adminPortalLabel).toBeVisible()
    
    // Check styling (optional but good for verification)
    await expect(adminPortalLabel).toHaveClass(/font-mono/)
    await expect(adminPortalLabel).toHaveClass(/uppercase/)
    await expect(adminPortalLabel).toHaveClass(/tracking-\[0.2em\]/)
  })
})
