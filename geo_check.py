"""
핫딜방 GEO 측정기 — AI 4개에 같은 질문을 던지고, 내 브랜드가 언급·인용되는지 기록합니다.
표준 라이브러리만 사용 (pip 설치 필요 없음).

환경변수(GitHub Secrets) — 있는 것만 측정합니다:
  OPENAI_API_KEY, GEMINI_API_KEY, PERPLEXITY_API_KEY, ANTHROPIC_API_KEY
모델 바꾸기(선택): OPENAI_MODEL, GEMINI_MODEL, PERPLEXITY_MODEL, ANTHROPIC_MODEL

입력:  questions.txt, brand.txt
출력:  docs/data/results.json (최신 1회), docs/data/history.json (최근 40회)
실행:  python geo_check.py            # 실제 측정
       python geo_check.py --dry-run  # API 호출 없이 형식만 확인
"""
import os, re, sys, time, datetime
from common import post, gemini, gemini_text, gemini_used, read_lines, load_json, save_json

DRY = "--dry-run" in sys.argv


ASK = "다음 질문에 한국 사용자에게 답하듯 구체적으로 답해줘. 추천할 만한 채널·사이트·계정이 있으면 이름을 밝혀줘.\n\n질문: "


def ask_openai(q):
    key = os.environ["OPENAI_API_KEY"]
    d = post("https://api.openai.com/v1/responses",
             {"model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
              "tools": [{"type": "web_search"}], "input": ASK + q},
             {"Authorization": "Bearer " + key})
    text, src = [], []
    for item in d.get("output", []):
        for c in item.get("content", []) or []:
            if c.get("type") == "output_text":
                text.append(c.get("text", ""))
                src += [a.get("url") for a in c.get("annotations", []) if a.get("url")]
    return "\n".join(text), src


def ask_gemini(q):
    # 모델은 common.gemini()가 고릅니다(기본 gemini-3.8-flash, 단종 시 자동 대체).
    d, model = gemini({"contents": [{"parts": [{"text": ASK + q}]}],
                       "tools": [{"google_search": {}}],
                       "generationConfig": {"maxOutputTokens": 4096}})
    cand = (d.get("candidates") or [{}])[0]
    text = gemini_text(d)
    if not text:
        raise RuntimeError(f"{model}: 빈 응답 (finishReason={cand.get('finishReason')})")
    chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks", [])
    # 제미나이는 출처 URL이 리다이렉트 주소라 제목(도메인)도 함께 남깁니다
    src = [(c.get("web", {}).get("title") or "") + " " + (c.get("web", {}).get("uri") or "") for c in chunks]
    return text, [s.strip() for s in src if s.strip()]


def ask_perplexity(q):
    key = os.environ["PERPLEXITY_API_KEY"]
    d = post("https://api.perplexity.ai/chat/completions",
             {"model": os.environ.get("PERPLEXITY_MODEL", "sonar"),
              "messages": [{"role": "user", "content": ASK + q}]},
             {"Authorization": "Bearer " + key})
    text = d["choices"][0]["message"]["content"]
    src = d.get("citations") or [r.get("url") for r in d.get("search_results", []) if r.get("url")]
    return text, src


def ask_claude(q):
    key = os.environ["ANTHROPIC_API_KEY"]
    d = post("https://api.anthropic.com/v1/messages",
             {"model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5"), "max_tokens": 1200,
              "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
              "messages": [{"role": "user", "content": ASK + q}]},
             {"x-api-key": key, "anthropic-version": "2023-06-01"})
    text, src = [], []
    for c in d.get("content", []):
        if c.get("type") == "text":
            text.append(c.get("text", ""))
            src += [x.get("url") for x in (c.get("citations") or []) if x.get("url")]
    return "".join(text), src


AIS = [("chatgpt", "OPENAI_API_KEY", ask_openai), ("gemini", "GEMINI_API_KEY", ask_gemini),
       ("perplexity", "PERPLEXITY_API_KEY", ask_perplexity), ("claude", "ANTHROPIC_API_KEY", ask_claude)]


def main():
    questions, brand = read_lines("questions.txt"), read_lines("brand.txt")
    pat = re.compile("|".join(re.escape(b) for b in brand), re.I) if brand else None
    active = [(n, f) for n, env, f in AIS if DRY or os.environ.get(env)]
    if not active:
        sys.exit("API 키가 하나도 없습니다. GitHub Secrets에 최소 1개를 넣어주세요.")
    results, errors = [], []
    for q in questions:
        for name, fn in active:
            try:
                text, src = ("(dry-run)", []) if DRY else fn(q)
            except Exception as e:  # 한 AI가 실패해도 나머지는 계속 측정
                errors.append({"q": q, "ai": name, "error": str(e)[:900]})
                print(f"[오류] {name} / {q}: {str(e)[:900]}")
                continue
            src = list(dict.fromkeys(s for s in src if s))[:10]
            in_text = bool(pat and pat.search(text))
            in_src = bool(pat and any(pat.search(s) for s in src))
            results.append({"q": q, "ai": name, "mentioned": in_text or in_src, "cited": in_src,
                            "sources": src, "snippet": text[:400]})
            print(f"{'●' if in_text or in_src else '○'} {name:<10} {q}")
            if not DRY:
                time.sleep(1)
    models = {}
    if gemini_used():
        models["gemini"] = gemini_used()
    run = {"run_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "brand": brand, "ais": [n for n, _ in active], "models": models,
           "results": results, "errors": errors}
    save_json("results.json", run)
    hist = load_json("history.json", [])
    hist.append({"run_at": run["run_at"], "results": [{k: r[k] for k in ("q", "ai", "mentioned", "cited", "sources")} for r in results]})
    save_json("history.json", hist[-40:])
    hit = sum(r["mentioned"] for r in results)
    print(f"\n완료: 답변 {len(results)}개 중 {hit}개에서 언급 ({hit / max(len(results), 1):.0%}), 오류 {len(errors)}개")
    if not results:
        sys.exit("모든 호출이 실패했습니다. 위 [오류] 줄을 확인하세요.")


if __name__ == "__main__":
    main()
