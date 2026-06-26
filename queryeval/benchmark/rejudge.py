# -*- coding: utf-8 -*-
"""Re-judge BM5 câu XUỐNG CẤP (hr_balance/leave_action + judge-fail) từ answer ĐÃ LƯU (KHÔNG re-fire).
Prompt đã sửa: HR src=0 BÌNH THƯỜNG (data từ hr_query tool, không phải document-source). Giữ kết quả tốt."""
import asyncio, json, os
from collections import defaultdict
import httpx
HERE=os.path.dirname(os.path.abspath(__file__))
JF=os.path.join(HERE,"..","results","benchmark5","llm_judge.jsonl")
LABELS=os.path.join(HERE,"..","questions","labels_single.jsonl")
KEY=os.environ.get("JUDGE_KEY") or os.environ.get("OPENROUTER_API_KEY","")  # set env, KHÔNG hardcode
MODEL="deepseek/deepseek-chat"
from llm_judge import JUDGE_SYS  # prompt đã sửa (HR src-agnostic)

lab={json.loads(l)["id"]:json.loads(l) for l in open(LABELS,encoding='utf-8') if l.strip()}
recs=[json.loads(l) for l in open(JF,encoding='utf-8') if l.strip()]

async def judge(c, item, answer, src, exp_oc):
    user=(f"CÂU HỎI: {item['q']}\n\nHÀNH VI/ĐÁP ÁN ĐÚNG (kỳ vọng): {item.get('expect','')}\n"
          f"LOẠI KỲ VỌNG: {exp_oc}\n\nCÂU TRẢ LỜI THỰC TẾ (số nguồn={src}):\n{answer or '(rỗng)'}")
    for _ in range(4):
        try:
            r=await c.post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {KEY}"},
                json={"model":MODEL,"messages":[{"role":"system","content":JUDGE_SYS},{"role":"user","content":user}],
                      "max_tokens":300,"temperature":0,"response_format":{"type":"json_object"}},timeout=60)
            d=json.loads(r.json()["choices"][0]["message"]["content"])
            return bool(d.get("correct")), str(d.get("why",""))[:80]
        except Exception: await asyncio.sleep(2)
    return None,"judge-fail"

def needs_rejudge(r):
    return (r["judge_correct"] is None) or (r["task_type"] in ("hr_balance","leave_action"))

async def main():
    targets=[r for r in recs if needs_rejudge(r)]
    print(f"re-judge {len(targets)}/{len(recs)} câu (hr/leave + judge-fail), giữ {len(recs)-len(targets)} kết quả tốt")
    sem=asyncio.Semaphore(4)
    async with httpx.AsyncClient(verify=False) as c:
        async def work(r):
            async with sem:
                item=lab.get(r["id"],{}); item.setdefault("q","");
                ok,why=await judge(c,item,r.get("answer",""),r.get("n_sources",0),r.get("expect_outcome","SUCCESS"))
                if ok is not None: r["judge_correct"]=ok; r["why"]="[rejudge] "+why
        await asyncio.gather(*[work(r) for r in targets])
    with open(JF,"w",encoding='utf-8') as f:
        for r in recs: f.write(json.dumps(r,ensure_ascii=False)+"\n")
    # aggregate cuối
    by=defaultdict(lambda:[0,0,0])
    for r in recs:
        v=by[r['task_type']]
        if r['judge_correct'] is None: v[2]+=1
        else: v[0]+=int(r['judge_correct']); v[1]+=1
    print("\n=== LLM-JUDGE BM5 (FINAL, sau re-judge hr/leave src-agnostic) ===")
    tot_ok=tot=0
    for cat in ["rag_info","hr_balance","leave_action","multiturn","ambiguous","offtopic_adv","no_doc"]:
        ok,j,fa=by[cat]; tot_ok+=ok; tot+=j
        print(f"  {cat:13s}: {ok}/{j} = {100*ok//j if j else 0}%"+(f"  (fail {fa})" if fa else ""))
    print(f"  {'TỔNG':13s}: {tot_ok}/{tot} = {100*tot_ok//tot if tot else 0}%")

if __name__=="__main__": asyncio.run(main())
