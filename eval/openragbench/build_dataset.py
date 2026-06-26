"""Build bộ eval OpenRAGBench cho test INGEST -> PRECISION trên hệ thống THẬT.

Tham khảo ý tưởng loader trong src/rag-worker/eval/pipeline_prototype.ipynb (HF dataset
gunnybd01/OpenRAGBench) NHƯNG viết lại cho mục đích khác: notebook đo in-memory; ở đây ta
chỉ TẢI corpus + TRÍCH LABEL ra đĩa để 1 harness riêng nạp qua document-service THẬT
(rag-worker parse/OCR/split/caption/embed/Qdrant + mcp rerank) rồi chấm precision.

LABEL (ground truth) lấy từ chính dataset: mỗi eval_pair = {query, gt_doc_id, type}
  - gt_doc_id = stem file PDF = đáp án đúng (doc-level). type: extractive | abstractive.
Đây là cách "lấy label" — KHÔNG cần gán nhãn tay.

Output (eval/openragbench/data/<N>/):
  corpus/*.pdf          # eval docs + distractor (nhiễu) — đổ vào hệ thống
  labels.jsonl          # {query_id, query, gt_doc_id, type}  <- ground truth precision
  manifest.json         # tóm tắt: #eval, #distractor, #queries, doc_ids

Chạy:  python eval/openragbench/build_dataset.py --n 50 --strategy balanced
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
from collections import defaultdict
from pathlib import Path

REPO_ID = "gunnybd01/OpenRAGBench"
OUT_ROOT = Path(__file__).parent / "data"


def _load_jsonl(filename: str) -> list[dict]:
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(repo_id=REPO_ID, filename=filename, repo_type="dataset")
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def _load_manifest() -> dict:
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(
        repo_id=REPO_ID, filename="eval/eval_manifest.json", repo_type="dataset"
    )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _sample_doc_ids(doc_to_pairs: dict, n_docs: int, strategy: str, rng: random.Random) -> list[str]:
    ids = list(doc_to_pairs.keys())
    has = lambda d, t: any(p["type"] == t for p in doc_to_pairs[d])  # noqa: E731
    if strategy == "random":
        return rng.sample(ids, min(n_docs, len(ids)))
    ext = [d for d in ids if has(d, "extractive")]
    ab = [d for d in ids if has(d, "abstractive")]
    if strategy == "hard":  # ưu tiên abstractive (khó hơn — cần tổng hợp, không trích thẳng)
        n_ab = min(n_docs, len(ab))
        rest = [d for d in ids if d not in set(ab)]
        return rng.sample(ab, n_ab) + rng.sample(rest, min(n_docs - n_ab, len(rest)))
    # balanced: giữ tỉ lệ extractive/abstractive như corpus gốc
    n_ext = round(n_docs * len(ext) / max(1, len(ids)))
    return rng.sample(ext, min(n_ext, len(ext))) + rng.sample(ab, min(n_docs - n_ext, len(ab)))


def _pull(hf_path: str, dst_dir: Path, flat_name: str) -> None:
    from huggingface_hub import hf_hub_download

    hf_hub_download(
        repo_id=REPO_ID, filename=hf_path, repo_type="dataset",
        local_dir=str(dst_dir), local_dir_use_symlinks=False,
    )
    nested = dst_dir / hf_path
    final = dst_dir / flat_name
    if nested.exists() and not final.exists():
        final.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(nested), str(final))


def build(n: int, strategy: str, seed: int, with_distractors: bool) -> dict:
    rng = random.Random(seed)
    print(f"OpenRAGBench: tải metadata (repo={REPO_ID})...")
    manifest = _load_manifest()
    all_pairs = manifest["eval_pairs"]
    corpus_meta = _load_jsonl("metadata/corpus_metadata.jsonl")
    total_docs, total_dist = manifest["eval_docs"], manifest["distractor_docs"]

    doc_to_pairs: dict[str, list] = defaultdict(list)
    for p in all_pairs:
        doc_to_pairs[p["gt_doc_id"]].append(p)

    sampled = _sample_doc_ids(doc_to_pairs, min(n, total_docs), strategy, rng)
    rng.shuffle(sampled)
    sset = set(sampled)
    pairs = [p for d in sampled for p in doc_to_pairs[d]]

    out = OUT_ROOT / str(len(sampled))
    if out.exists():
        shutil.rmtree(out)
    corpus_dir = out / "corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)

    print(f"Tải {len(sampled)} eval PDF...")
    got_eval = []
    for doc_id in sampled:
        try:
            _pull(f"corpus/eval_docs/{doc_id}.pdf", corpus_dir, f"{doc_id}.pdf")
            got_eval.append(doc_id)
        except Exception as e:  # noqa: BLE001
            print("  fail eval", doc_id, e)

    got_dist = []
    if with_distractors:
        n_dist = round(total_dist * len(sampled) / max(1, total_docs))
        dist = [
            m for m in corpus_meta
            if not m.get("is_eval_doc") and m["pdf_filename"].replace(".pdf", "") not in sset
        ]
        dist = rng.sample(dist, min(n_dist, len(dist)))
        print(f"Tải {len(dist)} distractor PDF (nhiễu — để đo precision thật)...")
        for m in dist:
            try:
                _pull(f"corpus/distractor_docs/{m['pdf_filename']}", corpus_dir, m["pdf_filename"])
                got_dist.append(m["pdf_filename"].replace(".pdf", ""))
            except Exception as e:  # noqa: BLE001
                print("  fail distractor", m["pdf_filename"], e)

    # labels.jsonl = ground truth precision (doc-level)
    labels_path = out / "labels.jsonl"
    with open(labels_path, "w", encoding="utf-8") as f:
        for i, p in enumerate(pairs):
            f.write(json.dumps({
                "query_id": f"q{i:04d}",
                "query": p["query"],
                "gt_doc_id": p["gt_doc_id"],
                "type": p.get("type", "?"),
            }, ensure_ascii=False) + "\n")

    meta = {
        "repo": REPO_ID, "strategy": strategy, "seed": seed,
        "eval_docs": got_eval, "distractor_docs": got_dist,
        "n_eval": len(got_eval), "n_distractor": len(got_dist), "n_queries": len(pairs),
        "corpus_dir": str(corpus_dir), "labels": str(labels_path),
    }
    (out / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nXONG: eval={len(got_eval)} distractor={len(got_dist)} queries={len(pairs)}")
    print(f"  corpus : {corpus_dir}")
    print(f"  labels : {labels_path}")
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50, help="số eval doc (mẫu)")
    ap.add_argument("--strategy", choices=["balanced", "random", "hard"], default="balanced")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-distractors", action="store_true", help="bỏ doc nhiễu (đo recall thuần)")
    args = ap.parse_args()
    build(args.n, args.strategy, args.seed, with_distractors=not args.no_distractors)
