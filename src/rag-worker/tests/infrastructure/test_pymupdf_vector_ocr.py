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

    def extract_image(self, xref):  # pragma: no cover - không dùng khi images=[]
        return {}


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
