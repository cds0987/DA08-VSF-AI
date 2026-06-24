import type { Conversation } from '~/types'

// Dựng snapshot mới để persist: deep-clone CHỈ conversation hiện tại; các conversation khác
// tái dùng object từ prevSnapshot (theo id) để tránh clone toàn bộ lịch sử mỗi lần ghi.
// Conversation chưa có trong prev (mới thêm / lần đầu) -> clone sâu. Giữ nguyên thứ tự.
export function buildHistorySnapshot(
  conversations: Conversation[],
  currentId: string | null,
  prevSnapshot: Conversation[],
): Conversation[] {
  const prevById = new Map(prevSnapshot.map(c => [c.id, c]))
  return conversations.map((c) => {
    if (c.id === currentId) {
      return { ...c, messages: c.messages.map(m => ({ ...m })) }
    }
    return prevById.get(c.id) ?? { ...c, messages: c.messages.map(m => ({ ...m })) }
  })
}
