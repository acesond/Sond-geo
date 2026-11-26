"""공용 도구: 설정 읽기, HTTP 호출, GitHub API."""
import json, os, urllib.request, urllib.parse, urllib.error

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
        raise RuntimeError(f"{method} {url.split('?')[0]} → {e.code}: {e.read().decode()[:400]}") from None


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
               "gemini-2.5-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash"]

_gemini = {"models": None, "used": None}


def gemini_available():
    """이 키로 generateContent가 되는 모델 이름 목록(실패하면 빈 목록)."""
    if _gemini["models"] is None:
        _gemini["models"] = []
        try:
            d = http("GET", "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                     None, {"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
            _gemini["models"] = [m.get("name", "").split("/")[-1] for m in d.get("models", []) or []
                                 if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        except Exception as e:
            print(f"[참고] Gemini 모델 목록 조회 실패: {str(e)[:160]}")
    return _gemini["models"]


def gemini_candidates(prefer=None):
    """시도할 모델 이름 순서: 지정값 → 알려진 이름 → 목록의 flash 모델 → 나머지."""
    avail = gemini_available()
    flash = sorted([m for m in avail if "flash" in m], key=lambda n: ("latest" not in n, len(n), n))
    order = [prefer or os.environ.get("GEMINI_MODEL") or GEMINI_DEFAULT] + GEMINI_PREF + flash + sorted(avail)
    out = []
    for m in order:
        if m and m not in out:
            out.append(m)
    return out


def gemini(body, prefer=None):
    """Gemini generateContent 호출 → (응답 JSON, 쓴 모델 이름).
    404(모델 단종·이름 변경)면 다음 후보로 넘어가고, 그 밖의 오류는 그대로 올립니다."""
    last = None
    for model in gemini_candidates(prefer):
        try:
            d = post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                     body, {"x-goog-api-key": os.environ["GEMINI_API_KEY"]})
            _gemini["used"] = model
            return d, model
        except RuntimeError as e:
            last = e
            if "404" in str(e) or "not found" in str(e).lower():
                print(f"[참고] Gemini 모델 '{model}' 없음 → 다음 후보로")
                continue
            raise
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
