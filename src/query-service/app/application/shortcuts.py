"""
Shared shortcut classification for the LangGraph agent.

Single source-of-truth for:
  - Shortcut phrase sets (identity, user-profile, clarify, security, off-topic)
  - Canned answers (Vietnamese with diacritics)
  - _normalize() / _phrase_match() helpers
  - classify_shortcut() — consumed by both shortcut_node and route_entry
"""

import random
import re
import unicodedata


# ---------------------------------------------------------------------------
# Sentinel for user-profile shortcut (filled dynamically in shortcut_node)
# ---------------------------------------------------------------------------

USER_PROFILE_PLACEHOLDER = "__user_profile__"


# ---------------------------------------------------------------------------
# Canned answers — proper Vietnamese with diacritics
# ---------------------------------------------------------------------------

IDENTITY_ANSWER = (
    "Mình là trợ lý nội bộ VinSmartFuture, hỗ trợ tra cứu chính sách, HR và tài liệu nội bộ."
)

CLARIFY_ANSWER = (
    "Chào bạn! Mình có thể hỗ trợ về chính sách, HR hoặc tài liệu nội bộ. "
    "Bạn nói rõ câu hỏi giúp mình nhé."
)

SECURITY_ANSWER = (
    "Mình không thể cung cấp tài khoản đặc quyền, mật khẩu, token hoặc thông tin truy cập nội bộ. "
    "Nếu bạn cần quyền cao hơn, vui lòng làm theo quy trình cấp quyền nội bộ."
)

# Three off-topic variants — rotated to avoid feeling robotic
_OFFTOPIC_VARIANTS = (
    "Câu hỏi này nằm ngoài phạm vi hỗ trợ của mình. "
    "Mình chỉ hỗ trợ về chính sách công ty, HR và tài liệu nội bộ.",

    "Mình chỉ có thể hỗ trợ các câu hỏi liên quan đến nội bộ công ty, HR hoặc tài liệu. "
    "Câu hỏi này nằm ngoài phạm vi đó.",

    "Rất tiếc, câu hỏi này không thuộc phạm vi hỗ trợ của mình — "
    "mình chỉ hỗ trợ chính sách, quy trình và dữ liệu HR nội bộ.",
)

def next_offtopic_answer() -> str:
    """Return a random off-topic canned response (thread-safe, no shared state)."""
    return random.choice(_OFFTOPIC_VARIANTS)


# Keep OFFTOPIC_ANSWER as the first variant for backward-compat imports
OFFTOPIC_ANSWER = _OFFTOPIC_VARIANTS[0]

EMERGENCY_ANSWER = (
    "⚠ Nếu đang ở nơi nguy hiểm, hãy rời khỏi khu vực đó ngay nếu có thể, "
    "báo bảo vệ/quản lý tòa nhà và gọi số khẩn cấp phù hợp (114 cứu hỏa, 115 cấp cứu). "
    "Nếu có người bị thương, hãy gọi cấp cứu ngay."
)

DISTRESS_ANSWER = (
    "Mình rất tiếc khi bạn đang cảm thấy như vậy. "
    "Nếu bạn đang không an toàn hoặc có nguy cơ làm hại bản thân/người khác, "
    "hãy liên hệ người thân, quản lý trực tiếp, HR hoặc dịch vụ khẩn cấp ngay. "
    "Nếu bạn muốn xin nghỉ vì sức khỏe, mình có thể hướng dẫn quy trình nghỉ phép/nghỉ ốm."
)


INJURY_ANSWER = (
    "Mình rất tiếc khi bạn bị thương. "
    "Nếu cần cấp cứu, hãy gọi 115 hoặc đến cơ sở y tế gần nhất. "
    "Nếu bạn muốn xin nghỉ ốm, mình có thể hướng dẫn quy trình nghỉ phép/nghỉ ốm — "
    "bạn muốn xem số ngày nghỉ còn lại hay quy trình nộp đơn?"
)

CROSS_USER_ANSWER = (
    "Mình chỉ có thể tra cứu dữ liệu HR cá nhân của chính bạn. "
    "Mình không thể cung cấp lương hoặc thông tin nhân sự của nhân viên khác hay phòng ban khác."
)


# ---------------------------------------------------------------------------
# Phrase sets
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Safety-critical phrase sets — checked deterministically BEFORE the LLM triage.
# All values are pre-normalized (lowercase, no diacritics, spaces only).
# Using multi-word phrases for ambiguous roots (e.g. "chay" = fire/run, "no" = explode/it)
# to prevent false positives.
# ---------------------------------------------------------------------------

EMERGENCY_PHRASES: frozenset[str] = frozenset({
    # Fire
    "chay roi", "bi chay", "phat chay", "hoa hoan", "chay no",
    # Explosion
    "no roi", "bi no", "phat no",
    # Flooding
    "ngap roi", "bi ngap", "ngap nuoc", "ngap lut", "lut roi",
    # Electrical
    "ro dien", "dien giat", "giat dien",
    # Smoke
    "boc khoi", "co khoi",
    # Injury / rescue
    "tai nan", "cap cuu", "bi thuong", "nguoi bi thuong", "mac ket", "bi ket",
    # Generic urgent
    "khan cap",
})

DISTRESS_PHRASES: frozenset[str] = frozenset({
    # Mental distress (multi-word to avoid single-token false positives)
    "dien roi", "phat dien", "do dien", "bi tam than",
    # Self-harm signals
    "khong muon song", "muon chet", "tu tu", "tuyet vong",
    # Mental health keywords
    "tram cam", "khong chiu noi", "chan song", "khung hoang",
})


# Physical injury — empathy + 115 + offer sick-leave guidance.
# Checked BEFORE distress so "gãy chân" routes here, NOT to distress.
# Uses multi-word phrases requiring both the body part and injury verb.
INJURY_PHRASES: frozenset[str] = frozenset({
    # Yêu cầu chủ ngữ hoặc "rồi" để phân biệt "đang báo chấn thương ngay lúc này"
    # với "gãy chân/chảy máu" xuất hiện như lý do xin nghỉ ốm ("nghỉ ốm do gãy chân").
    "toi gay chan", "toi bi gay chan", "gay chan roi",
    "toi gay tay",  "toi bi gay tay",  "gay tay roi",
    "toi gay xuong", "toi bi gay xuong", "gay xuong roi",
    "toi bi bong",  "bong nang roi",
    "toi chay mau", "dang chay mau",  "chay mau nhieu", "chay mau roi",
    "toi ngat xiu", "bi ngat xiu roi", "ngat xiu roi",
    "toi treo chan", "treo chan roi",
    "bi thuong nang",
})

# Cross-user data requests — REFUSE (asking for another person's personal HR data).
# MUST NOT match "của tôi" / "cua toi" — those are legitimate self-queries.
# Checked AFTER security, BEFORE it_support.
CROSS_USER_PHRASES: frozenset[str] = frozenset({
    "luong nhan vien",     # lương nhân viên
    "luong cua nhan vien", # lương của nhân viên
    "nhan vien phong",     # nhân viên phòng (Finance/HR/...)
    "luong phong",         # lương phòng
    "bang luong phong",    # bảng lương phòng
    "cua nguoi khac",      # của người khác
    "cua dong nghiep",     # của đồng nghiệp
    "don nghi cua nhan vien",  # đơn nghỉ của nhân viên
})


# Bot-identity questions: "Who are YOU?" (the assistant)
IDENTITY_PHRASES: frozenset[str] = frozenset({
    "ban la ai", "ban lam duoc gi", "ban co the lam gi",
    "gioi thieu ve ban", "who are you", "what can you do",
})

# User-identity questions: "Who am I?" (the logged-in user)
USER_PROFILE_PHRASES: frozenset[str] = frozenset({
    "toi la ai", "minh la ai", "day la ai",
    "who am i", "who i am",
    "thong tin tai khoan", "thong tin cua toi",
})

CLARIFY_PHRASES: frozenset[str] = frozenset({
    "alo", "hello", "hi", "xin chao", "chao",
    "mat bi sao vay", "tai sao lai the",
})

SECURITY_PHRASES: frozenset[str] = frozenset({
    # Credentials
    "mat khau", "password", "secret key", "api key",
    "access token", "credentials",
    # Elevated-access requests
    "tai khoan cap cao", "quyen admin", "quyen cao nhat",
    "nang quyen", "superuser", "admin account",
    "quan tri vien", "root access",
})

OFFTOPIC_PHRASES: frozenset[str] = frozenset({
    "mua", "mua gi", "can mua", "nha hang", "thoi tiet",
    "an com", "uong gi", "nau an", "bua an", "dau bep",
    "buy", "shop", "weather", "restaurant", "eat", "drink",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Lowercase, strip Vietnamese diacritics, collapse non-word chars to spaces."""
    without_accents = "".join(
        c for c in unicodedata.normalize("NFKD", text.lower())
        if not unicodedata.combining(c)
    )
    return re.sub(r"[\W]+", " ", without_accents, flags=re.UNICODE).strip()


def _phrase_match(normalized: str, phrases: frozenset[str]) -> bool:
    """
    Whole-word/phrase boundary match to avoid false positives from substring overlap.

    Pads both sides of *normalized* and each *phrase* with spaces so that a
    single-token phrase like "hi" only matches as a standalone word and never
    as part of a longer token (e.g. "nghi").  Multi-word phrases still match as
    a contiguous run because padding only wraps the outermost boundaries.
    """
    padded = f" {normalized} "
    return any(f" {p} " in padded for p in phrases)


def classify_shortcut(question: str) -> tuple[str, str] | None:
    """
    Check whether *question* matches a shortcut category.

    Returns (canned_response, outcome_str) if matched, or None to proceed to triage/think.
    outcome_str is one of: "SUCCESS", "REFUSE", "OFF_TOPIC", "CLARIFY".

    Check order (highest-priority first):
      emergency → injury → distress → identity → user_profile → security
      → cross_user → off_topic → clarify

    Notes:
    - injury is checked BEFORE distress so "gãy chân" routes to injury, not distress.
    - cross_user is checked AFTER security; it must not match "của tôi" self-queries
      (phrases are phrased to require "nhân viên"/"đồng nghiệp"/etc.).
    - IT support queries (máy tính hỏng, mất wifi, etc.) are NOT handled here —
      they fall through to triage → think → rag_search so internal runbooks are searched
      first; act_node escalates to IT Helpdesk only when RAG finds no relevant docs.

    USER_PROFILE_PLACEHOLDER is returned for user-identity questions — shortcut_node
    replaces it with the actual user profile from state.
    """
    normalized = normalize(question)

    # Safety-critical checks first — never let the LLM misroute these.
    if _phrase_match(normalized, EMERGENCY_PHRASES):
        return EMERGENCY_ANSWER, "SUCCESS"

    # Physical injury: empathy + 115 + sick-leave offer (distinct from mental distress).
    if _phrase_match(normalized, INJURY_PHRASES):
        return INJURY_ANSWER, "SUCCESS"

    if _phrase_match(normalized, DISTRESS_PHRASES):
        return DISTRESS_ANSWER, "SUCCESS"

    if _phrase_match(normalized, IDENTITY_PHRASES):
        return IDENTITY_ANSWER, "SUCCESS"

    if _phrase_match(normalized, USER_PROFILE_PHRASES):
        return USER_PROFILE_PLACEHOLDER, "SUCCESS"

    if _phrase_match(normalized, SECURITY_PHRASES):
        return SECURITY_ANSWER, "REFUSE"

    # Cross-user data request: asking for another person's salary / leave info → REFUSE.
    if _phrase_match(normalized, CROSS_USER_PHRASES):
        return CROSS_USER_ANSWER, "REFUSE"

    if _phrase_match(normalized, OFFTOPIC_PHRASES):
        return next_offtopic_answer(), "OFF_TOPIC"

    if _phrase_match(normalized, CLARIFY_PHRASES):
        return CLARIFY_ANSWER, "CLARIFY"

    return None
