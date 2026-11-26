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
