# -*- coding: utf-8 -*-
"""LLM-judge BM5: fire 150 câu labeled -> capture answer -> chấm bằng LLM (so expect + expect_outcome).
Thay outcome-heuristic (nhiễu light-route) bằng giám khảo LLM. -> accuracy CHÍNH XÁC per-category.
Env: ADMIN_PW LOADTEST_PW · OpenRouter key cho judge (JUDGE_KEY)."""
import asyncio, json, os, sys, time, uuid
from collections import defaultdict
import httpx
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "eval", "load20"))
from common import USER_API, QUERY_API, USER_PW, USER_EMAIL, parse_sse_line, classify_event  # noqa

LABELS=os.path.join(HERE, "..", "questions", "labels_single.jsonl")
OUT=os.path.join(HERE, "..", "results", "benchmark5", "llm_judge.jsonl")
JUDGE_KEY=os.environ.get("JUDGE_KEY") or os.environ.get("OPENROUTER_API_KEY","")  # set env, KHÔNG hardcode
JUDGE_MODEL="deepseek/deepseek-chat"
OCNAME={1:"REFUSE",2:"CLARIFY",3:"NO_INFO",4:"OFF_TOPIC",5:"SUCCESS"}
N_ACCT=20
CONC=6

JUDGE_SYS=("Bạn là GIÁM KHẢO chấm câu trả lời của trợ lý nhân sự nội bộ VinSmartFuture. "
"Chấm câu TRẢ LỜI THỰC TẾ có ĐÚNG so với KỲ VỌNG không. Trả về JSON: {\"correct\": true|false, \"why\":\"<ngắn>\"}.\n"
"⚠️ QUAN TRỌNG về 'số nguồn': số nguồn [N] CHỈ áp dụng cho tài liệu RAG. Dữ liệu HR CÁ NHÂN "
"(số ngày phép, lương, công) lấy từ HỆ THỐNG HR nội bộ qua công cụ hr_query — KHÔNG sinh ra source [N]. "
"Vì vậy hr_balance/leave_action có 'số nguồn=0' là BÌNH THƯỜNG, KHÔNG phải bịa. ĐỪNG chấm sai chỉ vì src=0.\n"
"Quy tắc theo LOẠI KỲ VỌNG:\n"
"- SUCCESS: đúng nếu trả lời ĐÚNG hướng nội dung cốt lõi khớp kỳ vọng. Với hr_balance (số dư phép cá nhân): "
"ĐÚNG nếu trả về MỘT con số cụ thể về số dư phép (số từ hệ thống HR — bạn KHÔNG cần kiểm số chính xác). "
"Với leave_action (tạo đơn nghỉ): đúng nếu xác nhận tạo đơn / hỏi mốc ngày hợp lý. Sai nếu từ chối nhầm, sai loại.\n"
"- CLARIFY: đúng nếu HỎI LẠI làm rõ (không bịa câu trả lời cho câu mơ hồ).\n"
"- REFUSE / OFF_TOPIC: đúng nếu TỪ CHỐI lịch sự (ngoài phạm vi nhân sự), KHÔNG trả lời nội dung ngoài lề.\n"
"- NO_INFO: đúng nếu nói KHÔNG tìm thấy/không có thông tin trong tài liệu (không bịa).")

async def fire(c, tok, uid, q):
    body={"user_id":uid,"question":q,"conversation_id":str(uuid.uuid4())}; ans=[]; oc=None; src=0
    try:
        async with c.stream("POST",f"{QUERY_API}/query",json=body,headers={"Authorization":f"Bearer {tok}"},timeout=httpx.Timeout(120,connect=20)) as rr:
            async for line in rr.aiter_lines():
                ev=parse_sse_line(line)
                if ev is None: continue
                k,v=classify_event(ev)
                if k=="answer": ans.append(v)
                elif k=="done": oc=ev.get("outcome"); src=len(ev.get("sources") or []); break
    except Exception as e: return ("", None, 0, str(e)[:40])
    return ("".join(ans), oc, src, None)

async def judge(c, item, answer, src):
    exp_oc=OCNAME.get(item.get("expect_outcome"),"SUCCESS")
    user=(f"CÂU HỎI: {item['q']}\n\nHÀNH VI/ĐÁP ÁN ĐÚNG (kỳ vọng): {item.get('expect','')}\n"
          f"LOẠI KỲ VỌNG: {exp_oc}\n\nCÂU TRẢ LỜI THỰC TẾ (số nguồn={src}):\n{answer[:1500] or '(rỗng)'}")
    for _ in range(2):
        try:
            r=await c.post("https://openrouter.ai/api/v1/chat/completions",headers={"Authorization":f"Bearer {JUDGE_KEY}"},
                json={"model":JUDGE_MODEL,"messages":[{"role":"system","content":JUDGE_SYS},{"role":"user","content":user}],
                      "max_tokens":300,"temperature":0,"response_format":{"type":"json_object"}},timeout=60)
            txt=r.json()["choices"][0]["message"]["content"]
            d=json.loads(txt); return bool(d.get("correct")), str(d.get("why",""))[:80]
        except Exception: await asyncio.sleep(1)
    return None, "judge-fail"

async def main():
    items=[json.loads(l) for l in open(LABELS,encoding='utf-8') if l.strip()]
    sem=asyncio.Semaphore(CONC)
    async with httpx.AsyncClient(verify=False) as c:
        # login
        toks=[]
        for i in range(1,N_ACCT+1):
            try:
                r=await c.post(f"{USER_API}/auth/login",json={"email":USER_EMAIL(i),"password":USER_PW},timeout=30)
                t=r.json()["access_token"]; me=await c.get(f"{USER_API}/auth/me",headers={"Authorization":f"Bearer {t}"},timeout=30)
                toks.append((t, me.json().get("id") or me.json().get("user_id")))
            except Exception: pass
        print(f"login {len(toks)} accounts · fire+judge {len(items)} câu (conc={CONC})")
        results=[]
        async def work(idx, item):
            async with sem:
                tok,uid=toks[idx%len(toks)]
                answer,oc,src,err=await fire(c,tok,uid,item['q'])
                if err: ok,why=None,f"fire-err:{err}"
                else: ok,why=await judge(c,item,answer,src)
                results.append({"id":item['id'],"task_type":item['task_type'],"expect_outcome":OCNAME.get(item.get('expect_outcome')),
                                "outcome_field":OCNAME.get(oc,oc),"n_sources":src,"judge_correct":ok,"why":why,"answer":answer[:200]})
                done=len(results)
                if done%15==0: print(f"  {done}/{len(items)}")
        await asyncio.gather(*[work(i,it) for i,it in enumerate(items)])
    with open(OUT,"w",encoding='utf-8') as f:
        for r in results: f.write(json.dumps(r,ensure_ascii=False)+"\n")
    # aggregate
    by=defaultdict(lambda:[0,0,0])  # correct, judged, fail
    for r in results:
        c2=by[r['task_type']]
        if r['judge_correct'] is None: c2[2]+=1
        else: c2[0]+=int(r['judge_correct']); c2[1]+=1
    print("\n=== LLM-JUDGE BM5 (deepseek-chat giám khảo) ===")
    tot_ok=tot=0
    for cat in ["rag_info","hr_balance","leave_action","multiturn","ambiguous","offtopic_adv","no_doc"]:
        ok,j,fa=by[cat]
        tot_ok+=ok; tot+=j
        print(f"  {cat:13s}: {ok}/{j} = {100*ok//j if j else 0}%"+(f" (judge-fail {fa})" if fa else ""))
    print(f"  {'TỔNG':13s}: {tot_ok}/{tot} = {100*tot_ok//tot if tot else 0}%  (heuristic cũ 75-76%)")
    print("DONE ->", os.path.normpath(OUT))

if __name__=="__main__": asyncio.run(main())
