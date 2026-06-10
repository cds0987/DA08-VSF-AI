import { expect, test } from '@playwright/test'

const adminSession = encodeURIComponent(JSON.stringify({
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Admin',
  email: 'admin@company.com',
  role: 'admin',
  department: 'IT',
  initials: 'AD',
}))

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([
    {
      name: 'eka.admin.session.user',
      value: adminSession,
      url: 'http://127.0.0.1:3001',
    },
    {
      name: 'eka.admin.access_token',
      value: 'frontend-upload-test-token',
      url: 'http://127.0.0.1:3001',
    },
  ])

  // Mock the /auth/me endpoint so the new middleware validation passes
  await page.route('**/api/user/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: '11111111-1111-4111-8111-111111111111',
        name: 'Admin',
        email: 'admin@company.com',
        role: 'admin',
        department: 'IT',
        initials: 'AD',
      }),
    })
  })

  await page.goto('/upload')
  await expect(page.getByRole('heading', { name: 'Upload Center' })).toBeVisible()
  await page.waitForFunction(() => Object.hasOwn(document.querySelector('#__nuxt') || {}, '__vue_app__'))
})

test('uploads a supported file with the expected multipart fields', async ({ page }) => {
  let uploadBody = ''
  let authorization = ''

  await page.route('**/documents/upload', async (route) => {
    uploadBody = route.request().postData() || ''
    authorization = route.request().headers().authorization || ''
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        document_id: '22222222-2222-4222-8222-222222222222',
        status: 'queued',
        message: 'Ingestion started',
      }),
    })
  })

  const [fileChooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.getByRole('button', { name: 'Select files' }).click(),
  ])
  await fileChooser.setFiles({
    name: 'employee-policy.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('Annual leave policy'),
  })
  await page.getByRole('button', { name: 'Upload All' }).click()

  await expect(page.getByText('employee-policy.txt', { exact: true })).toBeVisible()
  await expect(page.getByText('Ingestion started')).toBeVisible()
  expect(authorization).toBe('Bearer frontend-upload-test-token')
  expect(uploadBody).toContain('name="classification"')
  expect(uploadBody).toContain('internal')
  expect(uploadBody).toContain('name="file"; filename="employee-policy.txt"')
  expect(uploadBody).toContain('Annual leave policy')
})

test('blocks secret uploads without an allowed department', async ({ page }) => {
  let uploadRequests = 0
  await page.route('**/documents/upload', async (route) => {
    uploadRequests += 1
    await route.abort()
  })

  const [fileChooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.getByRole('button', { name: 'Select files' }).click(),
  ])
  await fileChooser.setFiles({
    name: 'secret-policy.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 test'),
  })

  const queueItem = page.getByRole('listitem').filter({ hasText: 'secret-policy.pdf' })
  await queueItem.locator('select').selectOption('secret')
  await page.getByRole('button', { name: 'Upload All' }).click()

  await expect(queueItem.getByText('At least one allowed department is required for secret documents', { exact: true })).toBeVisible()
  expect(uploadRequests).toBe(0)
})
