import { expect, test } from '@playwright/test'

const adminSession = encodeURIComponent(JSON.stringify({
  id: '11111111-1111-4111-8111-111111111111',
  name: 'Admin',
  email: 'admin@company.com',
  role: 'admin',
  department: 'IT',
  initials: 'AD',
}))

const MOCK_DEPARTMENTS = ['Engineering', 'Finance', 'HR']
const MOCK_USERS = [
  { id: 'aaaa-bbbb-cccc-0001', name: 'Alice Nguyen', email: 'alice@company.com' },
  { id: 'aaaa-bbbb-cccc-0002', name: 'Bob Tran', email: 'bob@company.com' },
]

test.beforeEach(async ({ context, page }) => {
  await context.addCookies([
    {
      name: 'eka.admin.session.user',
      value: adminSession,
      url: 'http://127.0.0.1:3001',
    },
    {
      name: 'eka.admin.access_token',
      value: 'frontend-acl-test-token',
      url: 'http://127.0.0.1:3001',
    },
  ])

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

  await page.route('**/api/hr/hr/departments', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ departments: MOCK_DEPARTMENTS }),
    })
  })

  await page.route('**/api/user/users*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: MOCK_USERS, total: MOCK_USERS.length }),
    })
  })

  await page.goto('/upload')
  await expect(page.getByRole('heading', { name: 'Upload Center' })).toBeVisible()
  await page.waitForFunction(() => Object.hasOwn(document.querySelector('#__nuxt') || {}, '__vue_app__'))
})

// ---------------------------------------------------------------------------
// Department picker
// ---------------------------------------------------------------------------

test('dept picker is disabled when default classification is not secret', async ({ page }) => {
  // Default is Internal — trigger should carry opacity-50
  const deptTrigger = page.locator('text=Select departments...').locator('..')
  await expect(deptTrigger).toHaveClass(/opacity-50/)
})

test('switching to Secret enables dept picker and shows departments from API', async ({ page }) => {
  await page.locator('select').first().selectOption('secret')

  const deptTrigger = page.locator('text=Select departments...').locator('..')
  await expect(deptTrigger).not.toHaveClass(/opacity-50/)

  await deptTrigger.click()

  for (const dept of MOCK_DEPARTMENTS) {
    await expect(page.getByText(dept).first()).toBeVisible()
  }
})

test('selecting a department from the picker shows it as a tag', async ({ page }) => {
  await page.locator('select').first().selectOption('secret')
  await page.locator('text=Select departments...').locator('..').click()

  await page.getByText('Engineering').first().click()

  // Tag should appear in the trigger area
  await expect(page.locator('text=Engineering').first()).toBeVisible()
  // Placeholder should be gone
  await expect(page.locator('text=Select departments...')).toHaveCount(0)
})

test('secret upload sends allowed_departments in multipart body', async ({ page }) => {
  let uploadBody = ''

  await page.route('**/documents/upload', async (route) => {
    uploadBody = route.request().postData() || ''
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ document_id: 'dddd-0001', status: 'queued', message: 'Ingestion started' }),
    })
  })

  // Switch to Secret and pick Finance
  await page.locator('select').first().selectOption('secret')
  await page.locator('text=Select departments...').locator('..').click()
  await page.getByText('Finance').first().click()
  // Close dropdown by clicking outside
  await page.keyboard.press('Escape')

  // Add a file
  const [fileChooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.getByRole('button', { name: 'Select files' }).click(),
  ])
  await fileChooser.setFiles({
    name: 'classified-report.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('confidential content'),
  })

  await page.getByRole('button', { name: 'Upload All' }).click()
  await expect(page.getByText('Ingestion started')).toBeVisible()

  expect(uploadBody).toContain('name="classification"')
  expect(uploadBody).toContain('secret')
  expect(uploadBody).toContain('name="allowed_departments"')
  expect(uploadBody).toContain('Finance')
})

// ---------------------------------------------------------------------------
// User picker
// ---------------------------------------------------------------------------

test('user picker is disabled when default classification is not top_secret', async ({ page }) => {
  const userTrigger = page.locator('text=Select users...').locator('..')
  await expect(userTrigger).toHaveClass(/opacity-50/)
})

test('switching to Top Secret enables user picker and shows user names not UUIDs', async ({ page }) => {
  await page.locator('select').first().selectOption('top_secret')

  const userTrigger = page.locator('text=Select users...').locator('..')
  await expect(userTrigger).not.toHaveClass(/opacity-50/)

  await userTrigger.click()

  await expect(page.getByText('Alice Nguyen').first()).toBeVisible()
  await expect(page.getByText('Bob Tran').first()).toBeVisible()
  // UUIDs should not be rendered as visible text
  await expect(page.getByText('aaaa-bbbb-cccc')).toHaveCount(0)
})

test('user picker search filters list by name', async ({ page }) => {
  await page.locator('select').first().selectOption('top_secret')
  await page.locator('text=Select users...').locator('..').click()

  await page.getByPlaceholder('Search by name or email...').fill('bob')

  await expect(page.getByText('Bob Tran').first()).toBeVisible()
  await expect(page.getByText('Alice Nguyen')).toHaveCount(0)
})

test('selecting a user shows name tag and upload sends UUID', async ({ page }) => {
  let uploadBody = ''

  await page.route('**/documents/upload', async (route) => {
    uploadBody = route.request().postData() || ''
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({ document_id: 'dddd-0002', status: 'queued', message: 'Ingestion started' }),
    })
  })

  // Switch to Top Secret and pick Alice
  await page.locator('select').first().selectOption('top_secret')
  await page.locator('text=Select users...').locator('..').click()
  await page.getByText('Alice Nguyen').first().click()

  // Tag must display name not UUID
  await expect(page.getByText('Alice Nguyen').first()).toBeVisible()
  await expect(page.locator('text=Select users...')).toHaveCount(0)

  // Add a file and upload
  const [fileChooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.getByRole('button', { name: 'Select files' }).click(),
  ])
  await fileChooser.setFiles({
    name: 'top-secret.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('eyes only'),
  })

  await page.getByRole('button', { name: 'Upload All' }).click()
  await expect(page.getByText('Ingestion started')).toBeVisible()

  expect(uploadBody).toContain('name="classification"')
  expect(uploadBody).toContain('top_secret')
  expect(uploadBody).toContain('name="allowed_user_ids"')
  expect(uploadBody).toContain('aaaa-bbbb-cccc-0001')
})

test('blocks top_secret upload without a selected user', async ({ page }) => {
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
    name: 'top-secret-no-user.pdf',
    mimeType: 'application/pdf',
    buffer: Buffer.from('%PDF-1.4 test'),
  })

  const queueItem = page.getByRole('listitem').filter({ hasText: 'top-secret-no-user.pdf' })
  await queueItem.locator('select').selectOption('top_secret')
  await page.getByRole('button', { name: 'Upload All' }).click()

  await expect(
    queueItem.getByText('At least one allowed user ID is required for top secret documents', { exact: true }),
  ).toBeVisible()
  expect(uploadRequests).toBe(0)
})
