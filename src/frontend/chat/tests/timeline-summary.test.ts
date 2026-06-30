import assert from 'node:assert/strict'
import test from 'node:test'
import { liveThoughtProse, summarizeThought, truncateFilename } from '../app/lib/timeline.ts'

// Gộp toàn bộ text của các section human-readable (KHÔNG gồm raw) — để khẳng định
// first-level detail không chứa dấu ngoặc/nháy JSON.
function detailText(detail: { label: string; lines: string[] }[]): string {
  return detail.map(s => `${s.label} ${s.lines.join(' ')}`).join(' ')
}

test('empty / nullish -> empty summary, no detail, no raw', () => {
  for (const value of [undefined, null, '', '   ']) {
    const r = summarizeThought(value as string | null | undefined)
    assert.equal(r.summary, '')
    assert.deepEqual(r.detail, [])
    assert.equal(r.raw, null)
  }
})

test('short plain text -> summary only, no disclosure', () => {
  const r = summarizeThought('Đang lập kế hoạch tra cứu chính sách nghỉ phép')
  assert.deepEqual(r.detail, [])
  assert.equal(r.raw, null)
  assert.match(r.summary, /chính sách/)
})

test('long plain text -> truncated summary + full text as a label-less detail section, no raw', () => {
  const long = 'từ '.repeat(120).trim()
  const r = summarizeThought(long)
  assert.ok(r.summary.endsWith('…'))
  assert.ok(r.summary.length <= 242)
  assert.equal(r.detail.length, 1)
  assert.equal(r.detail[0].label, '')
  assert.equal(r.detail[0].lines[0], long)
  assert.equal(r.raw, null)
})

test('JSON object -> human-readable labeled detail (no braces/quotes), raw JSON only second-level', () => {
  const raw = JSON.stringify({ route: 'heavy', reason: 'câu hỏi về chính sách nghỉ phép' })
  const r = summarizeThought(raw)
  // summary sạch
  assert.doesNotMatch(r.summary, /\[object Object\]|undefined|null/)
  // first-level detail: có nhãn người đọc được, KHÔNG có ngoặc/nháy JSON
  const text = detailText(r.detail)
  // route ('heavy') là jargon -> ẨN khỏi hiển thị (chỉ còn ở raw)
  assert.doesNotMatch(text, /Tuyến xử lý|heavy/)
  assert.match(text, /Lý do/)
  assert.match(text, /chính sách/)
  assert.doesNotMatch(text, /[{}"]/)
  // raw JSON nằm ở second-level (có ngoặc + xuống dòng)
  assert.ok(r.raw && r.raw.includes('\n') && r.raw.includes('"route"'))
})

test('JSON steps array -> KHÔNG surface "Các bước" (đã vẽ thành lane plan-step), chỉ còn ở raw', () => {
  const raw = JSON.stringify({
    route: 'heavy',
    reasoning: 'cần tra tài liệu rồi tổng hợp',
    steps: [
      { role: 'rag_retrieve', direction: 'tìm tài liệu liên quan' },
      { role: 'answer', direction: 'tổng hợp câu trả lời' },
    ],
  })
  const r = summarizeThought(raw)
  // steps KHÔNG còn hiện ở first-level (tránh trùng lane); route cũng ẩn
  assert.equal(r.detail.find(s => s.label === 'Các bước'), undefined)
  const text = detailText(r.detail)
  assert.doesNotMatch(text, /Các bước|Tuyến xử lý|tổng hợp câu trả lời/)
  assert.doesNotMatch(text, /[{}"]/)
  // summary = reasoning (sạch); steps vẫn còn ở raw cấp 2
  assert.match(r.summary, /tra tài liệu/)
  assert.ok(r.raw && r.raw.includes('"steps"'))
})

test('JSON with only nested objects -> neutral summary, empty first-level detail, raw available', () => {
  const raw = JSON.stringify({ meta: { a: 1 }, ctx: { b: 2 } })
  const r = summarizeThought(raw)
  assert.doesNotMatch(r.summary, /\[object Object\]|undefined|null/)
  assert.ok(r.summary.length > 0)
  // không bịa nhãn từ object lồng nhau -> first-level rỗng, dữ liệu vẫn còn ở raw
  assert.deepEqual(r.detail, [])
  assert.ok(r.raw && r.raw.includes('"meta"'))
})

// ── DEFENSIVE: BE có thể nhét raw JSON LẪN trong text (sai format) — FE phải chặn lộ ──

// Không bao giờ để dấu hiệu JSON/debug rò ra first-level (summary + detail human-readable).
function assertNoJsonLeak(r: { summary: string; detail: { label: string; lines: string[] }[] }) {
  const surface = `${r.summary} ${detailText(r.detail)}`
  assert.doesNotMatch(surface, /[{}]/, 'không được lộ ngoặc nhọn JSON')
  assert.doesNotMatch(surface, /"\w+"\s*:/, 'không được lộ cặp "key": JSON')
  assert.doesNotMatch(surface, /\[object Object\]|undefined|null|NaN/)
}

test('embedded JSON after a natural-language prefix -> human-readable detail, raw second-level only', () => {
  const raw = 'Output JSON.Mình hiểu bạn muốn biết nếu đi sớm thì có được thưởng gì không. '
    + JSON.stringify({
      route: 'heavy',
      reasoning: 'Mình hiểu bạn hỏi về việc đi sớm có được thưởng hay không',
      steps: [
        { id: 1, role: 'rag_retrieve', direction: 'Trích các điều khoản về thưởng' },
        { id: 2, role: 'synthesize_recommend', direction: 'kết quả từ step trước' },
      ],
    })
  const r = summarizeThought(raw)
  assertNoJsonLeak(r)
  // prefix NL hữu ích vẫn còn (đã bỏ nhiễu "Output JSON.")
  assert.match(r.summary, /Mình hiểu/)
  assert.doesNotMatch(r.summary, /Output JSON/)
  // detail có nhãn người đọc được
  const text = detailText(r.detail)
  assert.match(text, /Lý do|Các bước/)
  // raw JSON đầy đủ chỉ ở cấp 2
  assert.ok(r.raw && r.raw.includes('"route"') && r.raw.includes('\n'))
})

test('embedded JSON with prefix + suffix -> extracts first object, no raw leak', () => {
  const raw = 'Some prefix {"route":"heavy","reasoning":"vì abc","steps":[]} some suffix'
  const r = summarizeThought(raw)
  assertNoJsonLeak(r)
  assert.ok(r.raw && r.raw.includes('"route"'))
})

test('pure embedded JSON object (no useful prefix) -> labeled detail, no braces in first level', () => {
  const raw = '{"route":"heavy","reasoning":"chính sách thưởng","steps":[{"role":"rag_retrieve","direction":"tìm tài liệu"}]}'
  const r = summarizeThought(raw)
  assertNoJsonLeak(r)
  assert.match(detailText(r.detail), /Tuyến xử lý|Lý do|Các bước/)
  assert.ok(r.raw && r.raw.includes('"steps"'))
})

test('malformed JSON-like payload -> stripped, never dumped, raw is null', () => {
  const raw = 'Trả lời: {"route":"heavy", "reasoning": oops not valid json, steps missing'
  const r = summarizeThought(raw)
  assertNoJsonLeak(r)
  // không dump payload thô -> không có raw, summary giữ phần NL sạch
  assert.equal(r.raw, null)
  assert.match(r.summary, /Trả lời/)
})

test('plain text that merely mentions the word json -> untouched, no false strip', () => {
  const r = summarizeThought('Mình sẽ trả về json cho bạn sau khi tra cứu xong')
  assert.match(r.summary, /json/)
  assert.deepEqual(r.detail, [])
  assert.equal(r.raw, null)
})

test('orchestrator prose: cắt recap kỹ thuật ở đuôi (Plan:/input=/depends_on), giữ NL', () => {
  const raw = 'Chúng ta cần xử lý câu hỏi về chính sách nghỉ phép, thuộc phạm vi hỗ trợ nội bộ. '
    + 'Plan: 1 step rag_retrieve input=câu hỏi reasoning=tra tài liệu depends_on=[]'
  const r = summarizeThought(raw)
  assert.match(r.summary, /chính sách nghỉ phép/)
  const surface = `${r.summary} ${r.detail.map(s => s.lines.join(' ')).join(' ')}`
  assert.doesNotMatch(surface, /depends_on|input=|reasoning=|Plan:\s*\d/)
})

test('prose thường KHÔNG có marker kỹ thuật -> KHÔNG cắt nhầm', () => {
  const raw = 'Tôi sẽ lập kế hoạch tra cứu tài liệu rồi tổng hợp lại câu trả lời cho bạn'
  const r = summarizeThought(raw)
  assert.equal(r.summary, raw)
})

// REGRESSION (bug "1" của huuhung): prose chứa '[1]' (vd "depends_on [1]") đứng TRƯỚC khối JSON plan
// thật -> extractFirstJsonObject cũ parse '[1]' = mảng [1] -> summary RÁC "1". Phải BỎ QUA mảng toàn
// số, lấy object plan thật -> summary = reasoning/prose.
test('prose có "[1]" trước JSON plan -> KHÔNG tóm tắt thành "1", lấy reasoning thật', () => {
  const raw = 'Câu hỏi về bảo vệ. step2 synthesize_recommend depends_on [1].\n\n'
    + 'Để mình lập plan.\n{"route":"heavy","reasoning":"Cần tra cứu quy định trực bảo vệ nội bộ",'
    + '"steps":[{"id":1,"role":"rag_retrieve","input":"quy định trực bảo vệ","direction":"tìm tài liệu","depends_on":[]}]}'
  const r = summarizeThought(raw)
  assert.notEqual(r.summary.trim(), '1')
  assert.match(r.summary, /tra cứu quy định trực bảo vệ/)
})

test('mảng toàn primitive ([1], [1,2]) KHÔNG bị coi là JSON -> giữ nguyên prose', () => {
  const r1 = summarizeThought('Bước này phụ thuộc [1] và [2] nên làm sau')
  assert.match(r1.summary, /phụ thuộc/)
  assert.notEqual(r1.summary.trim(), '1')
})

// REGRESSION: lúc STREAM, object step con ('{id,role,input,direction,depends_on}') đóng TRƯỚC object
// ngoài -> KHÔNG được tóm tắt thành "id: 1 · role…" (đã render thành lane plan riêng).
test('object step nội bộ rời -> KHÔNG surface "id:.. role:.." (đã có lane plan)', () => {
  const raw = 'Đang lập kế hoạch tra cứu.\n{"id":1,"role":"rag_retrieve","input":"x","direction":"y","depends_on":[]}'
  const r = summarizeThought(raw)
  assert.doesNotMatch(r.summary, /^id:|role:\s*rag_retrieve/)
  assert.match(r.summary, /lập kế hoạch tra cứu/)
})

// "MỞ KHỐI suy luận gốc vẫn GỌN": phần CoT mở rộng KHÔNG được dump jargon planning (route heavy,
// tên role rag_retrieve/synthesize_recommend, "plan N steps") — đã render thành lane plan riêng.
// Cắt từ ĐẦU CÂU chứa jargon (không để mảnh cụt), GIỮ phần phân tích người-đọc-được.
test('mở suy luận gốc: cắt đuôi jargon planning (route heavy / tên role / plan N steps), giữ phân tích', () => {
  const raw = 'Đây là câu hỏi về lịch nghỉ lễ Tết của công ty, thuộc chính sách nhân sự nội bộ. '
    + 'Ta sẽ route heavy, dùng rag_retrieve để tra tài liệu. Nên plan 2 steps: rag_retrieve và synthesize_recommend.'
  const r = summarizeThought(raw)
  const surface = `${r.summary} ${r.detail.map(s => s.lines.join(' ')).join(' ')}`
  // jargon BỊ CẮT hết
  assert.doesNotMatch(surface, /route heavy|rag_retrieve|synthesize_recommend|plan 2 steps/i)
  // phân tích người-đọc-được GIỮ lại, KHÔNG để mảnh cụt "Ta sẽ"
  assert.match(surface, /lịch nghỉ lễ Tết của công ty/)
  assert.doesNotMatch(surface, /Ta sẽ\s*$/)
})

// REGRESSION (huuhung): stripPlanRecap CŨ cắt tại marker ĐẦU TIÊN -> khi role/route được nhắc SỚM
// trong suy luận thật, "suy luận gốc" bị xoá gần hết (có khi rỗng -> mất luôn nút "Xem suy luận gốc").
// Marker ở 40% ĐẦU = suy luận -> GIỮ NGUYÊN, không cắt.
test('role/route nhắc SỚM trong suy luận -> KHÔNG cắt (giữ nội dung "suy luận gốc")', () => {
  const raw = 'Mình cần dùng rag_retrieve để tra quy trình tăng lương định kỳ rồi đối chiếu với chính '
    + 'sách nội bộ, sau đó tổng hợp các bước cụ thể cho bạn về điều kiện, hồ sơ và thời gian xét duyệt.'
  const r = summarizeThought(raw)
  assert.match(r.summary, /tra quy trình tăng lương định kỳ/)   // suy luận giữ nguyên, không cụt
})

test('CoT dài + recap kỹ thuật ở ĐUÔI -> "suy luận gốc" GIỮ phân tích (không rỗng), cắt đuôi', () => {
  const analysis = 'Đây là câu hỏi follow-up về quy trình tăng lương định kỳ của công ty, thuộc chính sách nhân sự nội bộ. '.repeat(4)
  const raw = analysis + 'Vậy nên route heavy, dùng rag_retrieve rồi synthesize_recommend để tổng hợp.'
  const r = summarizeThought(raw)
  const surface = `${r.summary} ${r.detail.map(s => s.lines.join(' ')).join(' ')}`
  assert.match(surface, /quy trình tăng lương định kỳ/)                              // phân tích còn
  assert.doesNotMatch(surface, /route heavy|rag_retrieve|synthesize_recommend/i)     // recap đuôi bị cắt
  assert.ok(r.detail.some(s => !s.label), 'vẫn còn section "suy luận gốc" (không rỗng)')
})

test('truncateFilename keeps extension and adds ellipsis', () => {
  const t = truncateFilename('CNHC_Employee_Handbook_2024_final.pdf', 20)
  assert.ok(t.length <= 21)
  assert.ok(t.endsWith('.pdf'))
  assert.ok(t.includes('…'))
  assert.equal(truncateFilename('A.pdf', 20), 'A.pdf')
})

// ── liveThoughtProse: prose orchestrator LIVE, KHÔNG bao giờ lóe JSON (BE stream cả prose + JSON) ──

test('liveThoughtProse giữ prose thường nguyên văn', () => {
  assert.equal(liveThoughtProse('Đang tra cứu chính sách nghỉ phép'), 'Đang tra cứu chính sách nghỉ phép')
})

test('liveThoughtProse KHÔNG lóe ngoặc mở dở (trước khi có "key:") lúc stream', () => {
  // Khe giữa khi JSON mới mở, chưa tới dấu ':' đầu tiên — phải đã bị cắt, không lộ '{'/'['.
  for (const partial of ['Phân tích yêu cầu {', 'Phân tích yêu cầu {"route', 'Phân tích yêu cầu [{"id"']) {
    const r = liveThoughtProse(partial)
    assert.equal(r, 'Phân tích yêu cầu')
    assert.doesNotMatch(r, /[{[]/)
  }
})

test('liveThoughtProse cắt JSON dở ở đuôi (đã có "key:") khi đang stream', () => {
  const r = liveThoughtProse('Phân tích yêu cầu {"route":"hea')
  assert.equal(r, 'Phân tích yêu cầu')
  assert.doesNotMatch(r, /[{]|"route"/)
})

test('liveThoughtProse bóc JSON đầy đủ lẫn prose', () => {
  const r = liveThoughtProse('Tôi sẽ tra cứu. {"route":"heavy","steps":[{"id":1,"role":"rag_retrieve"}]}')
  assert.equal(r, 'Tôi sẽ tra cứu.')
  assert.doesNotMatch(r, /route|steps|[{]/)
})

test('liveThoughtProse giữ ngoặc cân bằng trong prose (không cắt nhầm)', () => {
  assert.equal(liveThoughtProse('dùng {var} ở đây'), 'dùng {var} ở đây')
})

test('liveThoughtProse rỗng/null -> chuỗi rỗng', () => {
  assert.equal(liveThoughtProse(''), '')
  assert.equal(liveThoughtProse(null), '')
  assert.equal(liveThoughtProse(undefined), '')
})
