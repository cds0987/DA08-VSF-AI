# TODO: RAG Engineer
# POST /search → RetrievalUseCase → List[SearchResult] Top-3
# Internal only — chỉ Chat Service gọi, không expose ra ngoài
from fastapi import APIRouter

router = APIRouter()
