import { expect, test } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import { readdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { adminUser, chatUser, encodeSessionCookie, mintJwt } from './helpers/cloudAuth'

const JWT_SECRET_KEY = process.env.JWT_SECRET_KEY
const CI_RECORD = process.env.CI_RECORD || '/tmp/ci_e2e_record.json'
const SPEC_DIR = path.dirname(fileURLToPath(import.meta.url))
const VALIDATION_DIR = path.resolve(SPEC_DIR, '../../../../rag-worker/eval/validation')
const ALLOWED_EXTENSIONS = new Set(['.pdf', '.docx', '.txt', '.xlsx', '.csv', '.pptx', '.md'])
const EXCLUDED_FILENAMES = new Set(['README.md'])
const CHAT_APP_URL = process.env.NUXT_PUBLIC_CHAT_APP_URL || 'http://127.0.0.1:3000'

const GOLDEN = [
  { query: 'how long until the password reset link expires', pattern: /(fifteen|mười lăm)/i },
  { query: 'how many annual leave days do full-time employees get', pattern: /(twelve|mười hai)/i },
  { query: 'how to report a security incident data breach', pattern: /(breach|vi phạm dữ liệu)/i },
  { query: 'how many days per week can employees work remotely', pattern: /(three|ba ngày)/i },
  { query: 'what is the daily meal allowance per diem for travel', pattern: /(fifty|50 usd|50)/i },
  { query: 'collect laptop and badge and attend orientation onboarding', pattern: /(orientation|định hướng)/i },
]

function validationFiles() {
  return readdirSync(VALIDATION_DIR)
    .filter((name) => ALLOWED_EXTENSIONS.has(path.extname(name).toLowerCase()))
    .filter((name) => !EXCLUDED_FILENAMES.has(name))
    .sort()
    .map((name) => path.join(VALIDATION_DIR, name))
}

test.describe('cloud-backed real frontend flow', () => {
  test.skip(!process.env.E2E_REAL_CLOUD, 'Set E2E_REAL_CLOUD=1 to run the real FE cloud flow.')
  test.skip(!JWT_SECRET_KEY, 'JWT_SECRET_KEY is required to mint FE session tokens.')

  test('uploads validation corpus in admin UI and answers golden queries in chat UI', async ({ browser }) => {
    test.setTimeout(10 * 60 * 1000)
    const files = validationFiles()
    expect(files.length).toBeGreaterThan(0)

    const adminToken = mintJwt(adminUser, JWT_SECRET_KEY!)
    const chatToken = mintJwt(chatUser, JWT_SECRET_KEY!)
    const uploadedDocs: Array<{ doc_id: string; gcs_key: string }> = []
    let uploadedIndex = 0

    const adminContext = await browser.newContext()
    await adminContext.addCookies([
      {
        name: 'eka.admin.session.user',
        value: encodeSessionCookie(adminUser),
        url: 'http://127.0.0.1:3001',
      },
      {
        name: 'eka.admin.access_token',
        value: adminToken,
        url: 'http://127.0.0.1:3001',
      },
    ])

    const adminPage = await adminContext.newPage()
    adminPage.on('response', async (response) => {
      if (!response.url().includes('/documents/upload') || response.status() !== 202) return
      const body = await response.json()
      const currentFile = files[uploadedIndex]
      if (!body?.document_id || !currentFile) return
      uploadedDocs.push({
        doc_id: body.document_id,
        gcs_key: `raw/${body.document_id}/${path.basename(currentFile)}`,
      })
      uploadedIndex += 1
      writeFileSync(CI_RECORD, JSON.stringify({ docs: uploadedDocs }, null, 2))
    })

    await adminPage.goto('/upload')
    await expect(adminPage.getByRole('heading', { name: 'Upload Center' })).toBeVisible()
    await adminPage.waitForFunction(() => Object.hasOwn(document.querySelector('#__nuxt') || {}, '__vue_app__'))
    await adminPage.locator('select').first().selectOption('public')

    const fileInput = adminPage.locator('input[type="file"]')
    await expect(fileInput).toHaveCount(1)
    await adminPage.getByRole('button', { name: 'Select files' }).click()
    try {
      const fileChooser = await adminPage.waitForEvent('filechooser', { timeout: 2_000 })
      await fileChooser.setFiles(files)
    } catch {
      await fileInput.setInputFiles(files)
    }

    await expect.poll(async () => adminPage.getByRole('listitem').count(), {
      message: 'validation files should appear in the upload queue',
      timeout: 15_000,
      intervals: [250, 500, 1_000],
    }).toBe(files.length)

    await adminPage.getByRole('button', { name: 'Upload All' }).click()

    await expect.poll(() => uploadedDocs.length, {
      message: 'all validation documents should be accepted by document-service',
      timeout: 180_000,
      intervals: [1_000, 2_000, 5_000],
    }).toBe(files.length)

    for (const filePath of files) {
      const item = adminPage.getByRole('listitem').filter({ hasText: path.basename(filePath) })
      await expect(item.getByText(/Indexed into \d+ chunks|indexed/i).first()).toBeVisible({ timeout: 360_000 })
    }

    const chatContext = await browser.newContext()
    await chatContext.addCookies([
      {
        name: 'eka.chat.session.user',
        value: encodeSessionCookie(chatUser),
        url: CHAT_APP_URL,
      },
      {
        name: 'eka.chat.access_token',
        value: chatToken,
        url: CHAT_APP_URL,
      },
    ])

    const chatPage = await chatContext.newPage()
    await chatPage.goto(`${CHAT_APP_URL}/chat`)
    await chatPage.waitForFunction(() => (window as Window & { __chatReady?: boolean }).__chatReady === true)
    await expect(chatPage.getByPlaceholder('Ask a question about FeatureMind policies, procedures, or knowledge...')).toBeVisible()

    const input = chatPage.getByPlaceholder('Ask a question about FeatureMind policies, procedures, or knowledge...')
    const sendButton = chatPage.getByRole('button', { name: 'Send' })
    for (const { query, pattern } of GOLDEN) {
      await input.evaluate((element, value) => {
        const textarea = element as HTMLTextAreaElement
        textarea.value = ''
        textarea.dispatchEvent(new Event('input', { bubbles: true }))
        textarea.value = value
        textarea.dispatchEvent(new Event('input', { bubbles: true }))
      }, query)
      await expect(sendButton).toBeEnabled({ timeout: 15_000 })
      await sendButton.click()
      await expect(chatPage.getByText(pattern).last()).toBeVisible({ timeout: 180_000 })
    }

    await adminContext.close()
    await chatContext.close()
  })
})
