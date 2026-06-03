"""Provider implementations cho VectorDB interface (provider-first).

Mỗi provider là MỘT package con (Qdrant · ChromaDB · Milvus) gồm HAI file implement
cho hai deployment, chọn theo `config.url`:

    providers/<db>/
        __init__.py   # build(config) — route theo url
        base.py       # phần dùng chung (mapping, access filter/post-filter)
        remote.py     # CÓ url  → service riêng, client async-native (async thuần)
        inprocess.py  # KO url  → embedded chạy thẳng trong service, sync + to_thread

CHỦ Ý không import sẵn provider nào ở đây: mỗi provider kéo dependency nặng riêng
(qdrant-client / chromadb / pymilvus). Registry import LAZY từng package, và `build()`
chỉ kéo đúng file deployment được chọn.
"""
