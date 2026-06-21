import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

// GATE (FE side): FE PHẢI render khúc agent THEO HỢP ĐỒNG SSE sinh ra (sse-contract.gen.ts),
// KHÔNG hardcode lại danh sách node. Dev nào hardcode lại / bỏ import contract -> test đỏ.
// Cặp với gate Python (test_sse_contract_enforcement.py) -> khóa 2 đầu.

const root = new URL('../../../', import.meta.url)
const read = (p: string) => readFile(new URL(p, root), 'utf8')

test('FE tiêu thụ hợp đồng SSE sinh ra (không hardcode node)', async () => {
  const [contractPy, genTs, steps, pipeline, store] = await Promise.all([
    read('query-service/app/agents/sse_contract.py'),
    read('frontend/chat/app/types/sse-contract.gen.ts'),
    read('frontend/chat/app/components/chat/MessageSteps.vue'),
    read('frontend/chat/app/components/chat/Pipeline.vue'),
    read('frontend/chat/app/stores/chat.ts'),
  ])

  // 1) Mọi node khai trong contract Python PHẢI có trong file TS sinh ra (codegen đồng bộ).
  const nodeKeys = [...contractPy.matchAll(/"(\w+)":\s*_nd\(/g)].map(m => m[1])
  assert.ok(nodeKeys.length >= 6, `parse được node từ sse_contract.py: ${nodeKeys}`)
  for (const n of nodeKeys) {
    assert.match(genTs, new RegExp(`"${n}":\\s*\\{`), `sse-contract.gen.ts thiếu node ${n} -> chạy gen lại`)
  }
  assert.match(genTs, /export function nodeGroup/)

  // 2) MessageSteps + Pipeline render GENERIC theo contract (import nodeGroup), KHÔNG hardcode
  //    lại bộ lọc node kiểu ['plan','orchestrate','think'].
  for (const [name, src] of [['MessageSteps', steps], ['Pipeline', pipeline]] as const) {
    assert.match(src, /from '~\/types\/sse-contract\.gen'/, `${name} phải import hợp đồng SSE`)
    assert.match(src, /nodeGroup\(/, `${name} phải gom node qua nodeGroup (contract), không hardcode`)
    assert.doesNotMatch(
      src,
      /'plan'\s*\|\|\s*t\.node\s*===\s*'orchestrate'/,
      `${name} còn hardcode danh sách node cũ -> phải dùng nodeGroup theo contract`,
    )
  }

  // 3) chat.ts dùng SSE_DONE_REQUIRED (contract) cho guard done-event (cảnh báo, không drop im).
  assert.match(store, /SSE_DONE_REQUIRED/, 'chat.ts phải dùng SSE_DONE_REQUIRED để guard done-event')
  assert.match(store, /done-event không hợp lệ/, 'chat.ts phải cảnh báo khi done-event thiếu field')
})
