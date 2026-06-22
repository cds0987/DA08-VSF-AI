"""Khóa hành vi MỚI: trang có-chữ + nhiều nét VẼ-VECTOR (chart/bảng) -> rasterize cả trang
cho OCR (vớt số trong chart vector mà get_images không thấy). Mock fitz để chạy không cần
PyMuPDF/PDF thật."""
from __future__ import annotations

import sys
import types

import pytest

from app.infrastructure.external import local_parser


class _FakePixmap:
    def tobytes(self, fmt: str) -> bytes:
        return b"PNGDATA"


class _FakePage:
    def __init__(self, text: str, drawings: int, images: list | None = None) -> None:
        self._text, self._drawings, self._images = text, drawings, images or []

    def get_text(self, kind: str) -> str:
        return self._text

    def get_images(self, full: bool = False) -> list:
        return self._images

    def get_drawings(self) -> list:
        return [{}] * self._drawings

    def get_pixmap(self, matrix=None, alpha: bool = False) -> _FakePixmap:
        return _FakePixmap()


class _FakeDoc:
    def __init__(self, pages: list[_FakePage]) -> None:
        self._pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._pages)

    def extract_image(self, xref):
        return {"ext": "png", "width": 100, "height": 100, "image": b"PNGDATA"}


def _install_fake_fitz(monkeypatch, pages: list[_FakePage]) -> None:
    mod = types.ModuleType("fitz")
    mod.open = lambda path: _FakeDoc(pages)
    mod.Matrix = lambda a, b: ("matrix", a, b)
    monkeypatch.setitem(sys.modules, "fitz", mod)


def _pdf(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_bytes(b"%PDF-1.4 dummy")
    return f


def test_text_page_with_vector_drawings_is_rasterized(tmp_path, monkeypatch):
    pages = [
        _FakePage("Bảng công tác phí", drawings=20),  # nhiều nét -> chart/bảng vector
        _FakePage("Đoạn văn thường", drawings=2),       # chữ thuần -> không raster
    ]
    _install_fake_fitz(monkeypatch, pages)
    reader = local_parser._make_pymupdf_reader({"vector_ocr": True, "vector_drawings_threshold": 12})
    step = reader(_pdf(tmp_path))
    assert len(step.pages[0].images) == 1  # vector page -> OCR cả trang
    assert len(step.pages[1].images) == 0  # text page -> không
    assert step.total_images() == 1


def test_vector_ocr_can_be_disabled(tmp_path, monkeypatch):
    pages = [_FakePage("Có chữ + chart", drawings=99)]
    _install_fake_fitz(monkeypatch, pages)
    reader = local_parser._make_pymupdf_reader({"vector_ocr": False})
    step = reader(_pdf(tmp_path))
    assert len(step.pages[0].images) == 0  # tắt cờ -> giữ hành vi cũ


def test_scanned_page_still_rasterized(tmp_path, monkeypatch):
    pages = [_FakePage("", drawings=0)]  # không text-layer -> scan
    _install_fake_fitz(monkeypatch, pages)
    reader = local_parser._make_pymupdf_reader({})
    step = reader(_pdf(tmp_path))
    assert len(step.pages[0].images) == 1  # bất biến cũ vẫn giữ


def test_vector_raster_capped_at_budget_does_not_fail(tmp_path, monkeypatch):
    # 30 trang chart-vector, trần 25 -> vector-raster CHỈ thêm tới budget (BỔ SUNG), KHÔNG raise.
    pages = [_FakePage("Trang có chữ + chart", drawings=30) for _ in range(30)]
    _install_fake_fitz(monkeypatch, pages)
    reader = local_parser._make_pymupdf_reader({"vector_ocr": True, "vector_drawings_threshold": 12,
                                                "max_ocr_pages": 25})
    step = reader(_pdf(tmp_path))          # KHÔNG ném ValueError
    assert step.total_images() == 25       # capped đúng trần
    assert sum(len(p.images) for p in step.pages[:25]) == 25  # 25 trang đầu có raster
    assert all(len(p.images) == 0 for p in step.pages[25:])   # còn lại bỏ qua (text-layer vẫn giữ)


def test_essential_images_over_cap_capped_not_failed(tmp_path, monkeypatch):
    # 30 trang SCAN (ảnh thiết yếu) > trần 25 -> GRACEFUL CAP: KHÔNG raise, OCR 25 trang đầu,
    # 5 trang sau bỏ qua (rỗng). Doc vẫn ingest thay vì fail 0 chunk.
    pages = [_FakePage("", drawings=0) for _ in range(30)]
    _install_fake_fitz(monkeypatch, pages)
    reader = local_parser._make_pymupdf_reader({"max_ocr_pages": 25})
    step = reader(_pdf(tmp_path))                 # KHÔNG ném
    assert step.total_images() == 25              # capped đúng trần (cost bounded)
    assert sum(len(p.images) for p in step.pages[:25]) == 25
    assert all(len(p.images) == 0 for p in step.pages[25:])


def test_embedded_images_over_cap_capped(tmp_path, monkeypatch):
    # 1 trang có text + 40 ảnh nhúng -> cap 25, KHÔNG raise; text-layer giữ nguyên.
    pages = [_FakePage("Có chữ", drawings=0, images=[(i,) for i in range(40)])]
    _install_fake_fitz(monkeypatch, pages)
    reader = local_parser._make_pymupdf_reader({"max_ocr_pages": 25})
    step = reader(_pdf(tmp_path))
    assert step.total_images() == 25
    assert step.pages[0].text == "Có chữ"
