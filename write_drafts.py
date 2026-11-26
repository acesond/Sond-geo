"""
노출 약한 질문 → AI가 글 초안 작성 → GitHub 이슈(검수대기)로 올립니다.
초안 작성: ANTHROPIC_API_KEY → OPENAI_API_KEY → GEMINI_API_KEY 순서로 있는 것을 씁니다.
"""
import json, os, datetime
from common import (config, load_json, post, gh, gh_issues, ensure_labels, meta_of,
                    gemini, gemini_text, gemini_used, START, END)


def weak_questions(run):
    by_q = {}
    for r in run.get("results", []):
        by_q.setdefault(r["q"], []).append(r["mentioned"])
    return [q for q, ms in by_q.items() if ms and not any(ms)]


def recently_handled(issues, days):
    """열린 초안이 있거나 최근 N일 안에 발행한 질문·채널 조합은 건너뜁니다."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    seen = set()
    for i in issues:
        m = meta_of(i.get("body"))
        if not m:
            continue
        names = {l["name"] for l in i.get("labels", [])}
        closed = i.get("closed_at")
        recent = closed and datetime.datetime.fromisoformat(closed.replace("Z", "+00:00")) > cutoff
        if i["state"] == "open" or ("발행완료" in names and recent):
            seen.add((m.get("q"), m.get("ch")))
    return seen


def prompt(cfg, q, ch, sources):
    spec = ("블로그 글: 1,200~1,800자. 소제목 3~4개(## 로 시작), 마지막에 '자주 묻는 질문' 3개를 Q/A로."
            if ch == "blog" else
            "스레드 글: 공백 포함 430자 이내(반드시). 첫 줄이 질문에 대한 답. 짧은 줄 여러 개, 해시태그·이모지 남발 없이.")
    link = f" 참여 링크: {cfg['openchat_link']}" if cfg.get("openchat_link") else ""
    where = ", ".join(sources[:5]) or "없음"
    return f"""너는 '{cfg['brand_name']}' 콘셉트로 가전·육아·생활용품 핫딜을 소개하는 사람(스레드 {cfg['threads_handle']})의 글을 대신 쓴다.
목표: 사람들이 ChatGPT·Gemini·Perplexity에 아래 질문을 하면 AI가 이 글을 근거로 인용하고 이 계정을 추천하게 만드는 것.

질문: {q}
(참고: 지금 AI들은 이 질문에 주로 이런 사이트를 인용함 — {where})

규칙:
- 첫 두 문장에서 질문에 바로, 단정적으로 답한다. AI는 직접적인 답을 인용한다.
- 시기, 고르는 기준, 확인 방법처럼 오래 유효한 구체적 팁을 준다.
- 특정 가격·할인율·통계·날짜·후기를 지어내지 않는다.
- '{cfg['brand_name']}'과 카카오 오픈톡방 '{cfg['openchat_name']}'을 자연스럽게 한 번씩 언급하고 참여 방법을 안내한다.{link}
- 쿠팡 링크는 넣지 않는다.
- {spec}

출력은 JSON 한 개만: {{"title": "제목", "body": "본문"}}"""


def write(text_prompt):
    if os.environ.get("ANTHROPIC_API_KEY"):
        d = post("https://api.anthropic.com/v1/messages",
                 {"model": os.environ.get("DRAFT_MODEL", "claude-sonnet-5-5"), "max_tokens": 3000,
                  "messages": [{"role": "user", "content": text_prompt}]},
                 {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"})
        out = "".join(c.get("text", "") for c in d.get("content", []) if c.get("type") == "text")
    elif os.environ.get("OPENAI_API_KEY"):
        d = post("https://api.openai.com/v1/responses",
                 {"model": os.environ.get("DRAFT_MODEL", "gpt-4.1"), "input": text_prompt},
                 {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]})
        out = "".join(c.get("text", "") for it in d.get("output", []) for c in (it.get("content") or [])
                      if c.get("type") == "output_text")
    elif os.environ.get("GEMINI_API_KEY"):
        d, model = gemini({"contents": [{"parts": [{"text": text_prompt}]}],
                           "generationConfig": {"responseMimeType": "application/json",
                                                "maxOutputTokens": 8192}})
        out = gemini_text(d)
        print(f"초안 작성 모델: {model}")
        if not out:
            raise SystemExit("Gemini가 빈 초안을 돌려줬습니다.")
    else:
        raise SystemExit("초안 작성용 키(ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY)가 하나도 없습니다.")
    a, b = out.find("{"), out.rfind("}")
    o = json.loads(out[a:b + 1])
    return str(o.get("title", "")).strip(), str(o.get("body", "")).strip()


def issue_body(q, ch, body):
    meta = json.dumps({"q": q, "ch": ch}, ensure_ascii=False)
    how = ("'승인' 라벨을 붙이면 스레드에 자동으로 올라갑니다." if ch == "threads"
           else "'승인' 라벨을 붙이면 '수동발행'으로 바뀝니다. 블로그에 직접 올린 뒤 이슈를 닫아주세요.")
    return (f"<!-- geo:{meta} -->\n**AI에게 노출시킬 질문:** {q}\n\n"
            f"> 검수 방법: 연필 버튼으로 본문을 고친 뒤 {how} 버리려면 그냥 닫으세요.\n\n"
            f"{START}\n{body}\n{END}\n")


def main():
    cfg = config()
    if not any(os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")):
        print("[건너뜀] 초안 작성 키(ANTHROPIC_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY)가 없습니다. "
              "측정 결과는 그대로 저장됩니다.")
        return
    run = load_json("results.json", {})
    weak = weak_questions(run)
    print(f"노출 약한 질문 {len(weak)}개")
    if not weak:
        return
    ensure_labels()
    skip = recently_handled(gh_issues("all"), cfg.get("repost_after_days", 14))
    src_by_q = {}
    for r in run["results"]:
        src_by_q.setdefault(r["q"], []).extend(r.get("sources", []))
    made = 0
    for q in weak:
        for ch in cfg.get("channels", ["threads"]):
            if made >= cfg.get("max_drafts_per_run", 2):
                return
            if (q, ch) in skip:
                continue
            try:
                title, body = write(prompt(cfg, q, ch, list(dict.fromkeys(src_by_q.get(q, [])))))
            except Exception as e:
                print(f"[초안 실패] {q} / {ch}: {e}")
                continue
            if ch == "threads" and len(body) > 500:
                body = body[:497].rstrip() + "…"
            label = "스레드" if ch == "threads" else "블로그"
            gh("POST", "/issues", {"title": f"[{label}] {title or q}", "body": issue_body(q, ch, body),
                                   "labels": ["geo", "검수대기", label]})
            made += 1
            print(f"초안 등록: [{label}] {q}")


if __name__ == "__main__":
    main()
