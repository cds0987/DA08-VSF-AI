# queryeval — Query-service benchmark & labeled questions

Bộ benchmark đánh giá **latency + correctness + hành vi dưới tải** của `query-service`
(MOSA orchestrator-workers) trên prod (`https://vsfchat.cloud`). Câu hỏi được **gắn nhãn**
(task type, expected outcome, expected facts) và **grounded trên corpus thật** trong Qdrant
(Bộ luật LĐ 2019, VSF lương, claude_test_hr_policy, sổ tay Vintravel/MeKong/BlueOcean, doc ảnh).

> Mục tiêu ưu tiên: **giảm latency**. Benchmark này định lượng nút thắt theo từng stage
> (plan / verify / worker) và theo từng loại task, đồng thời đo độ suy giảm dưới tải.

## Cấu trúc

```
queryeval/
  questions/
    labels_single.jsonl       # 150 câu 1-lượt: rag_info, hr_balance, leave_action,
                              #   multiturn, ambiguous, offtopic_adv, no_doc
    labels_multiagent.jsonl   # 145 câu compound/so-sánh ÉP fan-out >=2 worker song song
  benchmark/
    dataset_single.py         # sinh labels_single.jsonl
    dataset_multiagent.py     # sinh labels_multiagent.jsonl
    run_load.py               # open-loop tại RATE cố định (vd 10 req/s) — đo saturation/single
    run_ramp.py               # closed-loop ramp concurrency (đợt 2) — tìm ngưỡng, không pile-up
    scrape_traces.js          # lấy span-tree/stage-latency từ Langfuse (Playwright)
    aggregate.py              # tổng hợp: latency, fan-out %, stage share, degradation
  results/                    # output (jsonl + json)
```

## Nhãn (schema mỗi dòng JSONL)

```jsonc
{ "id": "...", "task_type": "rag_info|hr_balance|leave_action|multiturn|ambiguous|offtopic_adv|no_doc|multiagent",
  "subtype": "...",            // chỉ multiagent
  "q": "<câu hỏi>",
  "expect": "<mô tả đáp án đúng / hành vi đúng để chấm tay>",
  "expect_outcome": 5,          // 1 REFUSE,2 CLARIFY,3 NO_INFO,4 OFF_TOPIC,5 SUCCESS
  "group": "g1", "turn": 2,     // chỉ multiturn (cùng conversation_id)
  "expect_min_workers": 2 }     // chỉ multiagent
```

## Tài khoản (purpose-built test) — creds qua ENV, KHÔNG hardcode

- `admin@company.com` (mật khẩu ở env `ADMIN_PW`)
- `loadtest01..20@company.com` (mật khẩu ở env `LOADTEST_PW`; seed qua `eval/load20/seed_users.py`)
- Langfuse scrape: `LF_BASIC_USER`/`LF_BASIC_PW` (nginx), `LF_EMAIL`/`LF_PW` (app login).

```bash
export ADMIN_PW=... LOADTEST_PW=... LF_BASIC_USER=... LF_BASIC_PW=... LF_EMAIL=... LF_PW=...
```

## Chạy

```bash
# 1. (re)generate labels
python benchmark/dataset_single.py
python benchmark/dataset_multiagent.py

# 2a. single 1-lượt (latency/correctness sạch) — open-loop nhịp thấp
PYTHONUTF8=1 python benchmark/run_load.py --rate 1 --dataset single

# 2b. ramp closed-loop (đợt 2 — tìm ngưỡng chịu tải, KHÔNG pile-up)
PYTHONUTF8=1 python benchmark/run_ramp.py

# 2c. burst open-loop (đợt 3 — saturation) — 10 req/s, 145 câu multi-agent
PYTHONUTF8=1 python benchmark/run_load.py --rate 10 --limit 145 --dataset multiagent

# 3. lấy stage-latency từ Langfuse (cần state.json cookie hoặc login)
NODE_PATH=<playwright> node benchmark/scrape_traces.js \
    results/load_results.jsonl results/load_trees.json [state.json]

# 4. tổng hợp
python benchmark/aggregate.py results/load_results.jsonl results/load_trees.json
```

## Chấm correctness

Chưa có API key judge trong repo → chấm **bằng tay** dựa trên trường `expect` (doc-grounded
assertion). Khi có `OPENAI_API_KEY`, có thể nối vào `eval/lib/metrics.py::run_ragas`
(faithfulness / answer_correctness / answer_relevancy, ngưỡng tại `eval/lib/metrics.py`).

## Kết quả & phát hiện

Xem [FINDINGS.md](FINDINGS.md).
