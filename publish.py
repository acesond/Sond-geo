"""
'승인' 라벨이 붙은 초안을 발행합니다.
- 스레드: Threads API로 바로 게시 (THREADS_ACCESS_TOKEN, THREADS_USER_ID 필요)
- 블로그: 글쓰기 API가 없어서 '수동발행' 라벨로 바꾸고 안내 댓글을 남깁니다.
사용: python publish.py <이슈번호>
"""
import sys, os, time, urllib.parse
from common import gh, http, meta_of, text_of, with_disclosure

API = "https://graph.threads.net/v1.0"


def threads_post(text):
    token, uid = os.environ["THREADS_ACCESS_TOKEN"], os.environ["THREADS_USER_ID"]
    q = urllib.parse.urlencode({"media_type": "TEXT", "text": text, "access_token": token})
    cid = http("POST", f"{API}/{uid}/threads?{q}")["id"]
    time.sleep(5)
    q = urllib.parse.urlencode({"creation_id": cid, "access_token": token})
    mid = http("POST", f"{API}/{uid}/threads_publish?{q}")["id"]
    try:
        link = http("GET", f"{API}/{mid}?fields=permalink&access_token={urllib.parse.quote(token)}").get("permalink", "")
    except RuntimeError:
        link = ""
    return mid, link


def relabel(n, remove, add):
    for name in remove:
        try:
            gh("DELETE", f"/issues/{n}/labels/{urllib.parse.quote(name)}")
        except RuntimeError:
            pass
    gh("POST", f"/issues/{n}/labels", {"labels": add})


def main(n):
    issue = gh("GET", f"/issues/{n}")
    names = {l["name"] for l in issue["labels"]}
    meta = meta_of(issue.get("body"))
    if "승인" not in names or "발행완료" in names or not meta:
        print("발행 대상이 아닙니다.")
        return
    text = with_disclosure(text_of(issue["body"]))
    if meta.get("ch") != "threads":
        relabel(n, ["검수대기", "승인"], ["수동발행"])
        gh("POST", f"/issues/{n}/comments", {"body": "블로그는 자동 발행이 안 돼서 직접 올려주세요. 본문을 복사해 올린 뒤 이 이슈를 닫으면 '발행 기록'에 남습니다."})
        return
    if not (os.environ.get("THREADS_ACCESS_TOKEN") and os.environ.get("THREADS_USER_ID")):
        relabel(n, ["승인"], ["수동발행"])
        gh("POST", f"/issues/{n}/comments", {"body": "THREADS_ACCESS_TOKEN / THREADS_USER_ID 시크릿이 없어 자동 게시를 못 했어요. 직접 올린 뒤 이슈를 닫아주세요."})
        return
    if len(text) > 500:
        relabel(n, ["승인"], ["검수대기"])
        gh("POST", f"/issues/{n}/comments", {"body": f"본문이 {len(text)}자예요. 스레드는 500자까지라 줄여서 다시 '승인'을 붙여주세요."})
        return
    try:
        mid, link = threads_post(text)
    except Exception as e:
        relabel(n, ["승인"], ["발행실패"])
        gh("POST", f"/issues/{n}/comments", {"body": f"스레드 게시 실패: `{str(e)[:300]}`\n토큰이 만료됐을 수 있어요(60일). README의 토큰 갱신 방법을 확인하세요. 고친 뒤 '발행실패'를 지우고 '승인'을 다시 붙이면 재시도합니다."})
        raise SystemExit(1)
    relabel(n, ["검수대기", "승인", "발행실패"], ["발행완료"])
    gh("POST", f"/issues/{n}/comments", {"body": f"스레드에 올렸어요. {link or ('게시물 ID ' + mid)}"})
    gh("PATCH", f"/issues/{n}", {"state": "closed"})


if __name__ == "__main__":
    main(int(sys.argv[1]))
