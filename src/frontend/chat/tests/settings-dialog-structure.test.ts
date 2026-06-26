import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const root = new URL('../', import.meta.url)
const read = (path: string) => readFile(new URL(path, root), 'utf8')

test('SettingsDialog uses DeepSeek-style sections without Data tab or destructive account actions', async () => {
  const src = await read('app/components/SettingsDialog.vue')

  assert.match(src, /useSessionStore/)
  assert.match(src, /activeSection/)
  assert.match(src, /label:\s*'General'/)
  assert.match(src, /label:\s*'Profile'/)
  assert.match(src, /label:\s*'About'/)
  assert.doesNotMatch(src, /label:\s*'Data'/)
  assert.doesNotMatch(src, /Delete account|Log out all devices|Clear chat history/)
})

test('SettingsDialog keeps theme controls and profile fields backed by existing frontend state', async () => {
  const src = await read('app/components/SettingsDialog.vue')

  assert.match(src, /value:\s*'light'/)
  assert.match(src, /value:\s*'dark'/)
  assert.match(src, /value:\s*'system'/)
  assert.match(src, /setTheme\(item\.value\)/)
  assert.match(src, /session\.user\?\.email/)
  assert.match(src, /session\.user\?\.role/)
  assert.match(src, /session\.user\?\.department/)
  assert.match(src, /session\.user\?\.is_active/)
})
