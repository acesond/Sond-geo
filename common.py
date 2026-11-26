"""공용 도구: 설정 읽기, HTTP 호출, GitHub API."""
import json, os, time, urllib.request, urllib.parse, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "docs", "data")
TIMEOUT = 120


def path(*p):
    return os.path.join(HERE, *p)


def read_lines(name):
    with open(path(name), encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]


def config():
    with open(path("config.json"), encoding="utf-8") as f:
        return json.load(f)


def load_json(name, default):
    try:
        with open(os.path.join(DATA, name), encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(name, obj):
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, name), "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def http(method, url, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json", "User-Agent": "sond-geo", **(headers or {})}
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        raise RuntimeError(f"{method} {url.split('?')[0]} → {e.code}: {detail[:900]}") from None


def post(url, body, headers):
    return http("POST", url, body, headers)


# ---------- GitHub ----------
def gh(method, endpoint, body=None):
    repo = os.environ["GITHUB_REPOSITORY"]
    url = f"https://api.github.com/repos/{repo}{endpoint}"
    return http(method, url, body, {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
                                    "Accept": "application/vnd.github+json"})


def gh_issues(state="all"):
    out, page = [], 1
    while True:
        batch = gh("GET", f"/issues?state={state}&labels=geo&per_page=100&page={page}")
        out += [i for i in batch if "pull_request" not in i]
        if len(batch) < 100:
            return out
        page += 1


LABELS = {"geo": "6b6f78", "검수대기": "ffd60a", "승인": "e8312a", "발행완료": "16181d",
          "수동발행": "0b4f8a", "발행실패": "b60205", "스레드": "000000", "블로그": "03c75a"}


def ensure_labels():
    have = {l["name"] for l in gh("GET", "/labels?per_page=100")}
    for name, color in LABELS.items():
        if name not in have:
            gh("POST", "/labels", {"name": name, "color": color})


# ---------- Gemini ----------
# 구글이 모델을 단종·개편하면 404("no longer available ...")가 납니다.
# 기본값은 최신 flash 모델, 404면 실제 사용 가능한 모델 목록에서 골라 다시 시도합니다.
GEMINI_DEFAULT = "gemini-3.8-flash"
GEMINI_PREF = ["gemini-3.8-flash", "gemini-3-flash", "gemini-3.8-flash-preview",
               "gemini-flash-latest", "gemini-flash-lite-latest",
               "gemini-2.5-flash", "gemini-2.0-flash"]
# 텍스트 답변용이 아닌 모델(음성·이미지·임베딩·실험 모델)은 후보에서 뺍니다.
GEMINI_SKIP = ("tts", "image", "embedding", "audio", "live", "veo", "imagen", "robotics",
               "antigravity", "omni", "vision", "learnlm", "gemma", "computer")
# 다시 시도해볼 만한 응답: 404(모델 없음) · 429(쿼터) · 503(과부하) · 400(도구 미지원 등)
GEMINI_RETRY = ("400", "404", "429", "503")
MAX_MODELS = 10  # 질문 하나에 시도할 모델 수 상한(무료 키 쿼터 소모·실행 시간 억제)

_gemini = {"models": None, "used": None, "preferred": None, "dead": set(), "no_tools": set()}


def gemini_available():
    """이 키로 generateContent가 되는 모델 이름 목록(실패하면 빈 목록)."""
    if _gemini["models"] is None:
        _gemini["models"] = []
        try:
            d = http("GET", "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                     None, {"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
            _gemini["models"] = [m.get("name", "").split("/")[-1] for m in d.get("models", []) or []
                                 if "generateContent" in (m.get("supportedGenerationMethods") or [])
                                 and not any(s in m.get("name", "").lower() for s in GEMINI_SKIP)]
        except Exception as e:
            print(f"[참고] Gemini 모델 목록 조회 실패: {str(e)[:160]}")
    return _gemini["models"]


def gemini_candidates(prefer=None):
    """시도할 모델 이름 순서: 이번에 성공한 모델 → 지정값 → 알려진 이름 → 목록의 flash 모델 → 나머지."""
    avail = gemini_available()
    flash = sorted([m for m in avail if "flash" in m], key=lambda n: ("latest" not in n, len(n), n))
    named = [prefer or os.environ.get("GEMINI_MODEL") or GEMINI_DEFAULT] + GEMINI_PREF
    order = ([_gemini["preferred"]] if (_gemini["preferred"] and not prefer) else []) + named + flash + sorted(avail)
    out = []
    for m in order:
        if m and m not in out:
            out.append(m)
    return out[:MAX_MODELS]


def gemini(body, prefer=None, tools=None):
    """Gemini generateContent 호출 → (응답 JSON, 쓴 모델 이름).
    404·429·503이면 다음 모델로 넘어가고, 그 밖의 오류는 그대로 올립니다.
    tools: [{"google_search": {}}] 처럼 웹검색 도구를 넘길 수 있습니다(미지원 모델은 자동으로 빠집니다).
    """
    last = None
    for wait_round in (0, 1):
        throttled = False
        blocked_otherwise = False
        for model in gemini_candidates(prefer):
            if model in _gemini["dead"]:
                continue
            b = dict(body)
            if tools and model not in _gemini["no_tools"]:
                b["tools"] = tools
            slowed = False
            while True:
                try:
                    d = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                             b, {"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
                    _gemini["used"] = _gemini["preferred"] = model
                    return d, model
                except Exception as e:
                    last = e
                    msg = str(e)
                    code = next((c for c in GEMINI_RETRY if f" {c}:" in msg), None)
                    if code is None and (isinstance(e, TimeoutError) or "timed out" in msg):
                        code = "timeout"
                    if code is None:  # 403 같은 권한 문제는 모델을 바꿔도 같습니다
                        raise
                    if code == "400" and "tool" in msg.lower() and "tools" in b:
                        print(f"[참고] Gemini '{model}'은 웹검색 도구 미지원 → 도구 없이 재시도")
                        _gemini["no_tools"].add(model)
                        b.pop("tools", None)
                        continue
                    if code == "404":
                        _gemini["dead"].add(model)  # 이번 실행에서는 다시 안 물어봅니다
                    if code in ("429", "503") and not slowed:
                        slowed = True
                        time.sleep(3)
                        continue
                    print(f"[참고] Gemini '{model}' 사용 불가({code}) → 다음 모델로")
                    if code in ("429", "503", "timeout"):
                        throttled = True
                    else:
                        blocked_otherwise = True
                    break
        # 모든 모델이 한도·과부하로만 막혔으면 잠시 쉬었다가 한 번 더 시도합니다.
        if not throttled or blocked_otherwise or wait_round == 1:
            break
        print("[참고] 모든 Gemini 모델이 한도·과부하 상태 → 60초 쉬고 다시 시도")
        time.sleep(60)
    raise last or RuntimeError("Gemini 모델을 찾지 못했습니다.")


def gemini_text(d):
    cand = (d.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()


def gemini_used():
    return _gemini["used"]


# ---------- 초안 본문 형식 ----------
START, END = "<!-- 본문 시작 (이 아래를 고쳐도 됩니다) -->", "<!-- 본문 끝 -->"


def meta_of(body):
    """이슈 본문 맨 위 <!-- geo:{...} --> 에서 질문·채널을 꺼냅니다."""
    body = body or ""
    if body.startswith("<!-- geo:"):
        try:
            return json.loads(body[len("<!-- geo:"):body.index("-->")].strip())
        except ValueError:
            pass
    return {}


def text_of(body):
    body = (body or "").replace("\r\n", "\n")
    if START in body and END in body:
        return body.split(START, 1)[1].split(END, 1)[0].strip()
    return body.strip()


DISCLOSURE = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."


def with_disclosure(text):
    """쿠팡 링크가 들어간 글에는 대가성 고지 문구를 꼭 붙입니다."""
    if ("coupang.com" in text or "coupa.ng" in text) and "쿠팡 파트너스" not in text:
        return text.rstrip() + "\n\n" + DISCLOSURE
    return text
