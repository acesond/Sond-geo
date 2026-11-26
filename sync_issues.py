"""초안 이슈 상태를 docs/data/drafts.json으로 정리해 대시보드가 읽게 합니다."""
from common import gh_issues, meta_of, text_of, save_json


def status(i, names):
    if "발행완료" in names or (i["state"] == "closed" and "수동발행" in names):
        return "published"
    if i["state"] == "closed":
        return "dropped"
    if "발행실패" in names:
        return "failed"
    if "수동발행" in names:
        return "manual"
    if "승인" in names:
        return "approved"
    return "review"


def main():
    out = []
    for i in gh_issues("all"):
        names = {l["name"] for l in i.get("labels", [])}
        m = meta_of(i.get("body"))
        if not m:
            continue
        st = status(i, names)
        out.append({"n": i["number"], "url": i["html_url"], "title": i["title"], "q": m.get("q", ""),
                    "ch": m.get("ch", ""), "status": st, "created": i["created_at"],
                    "published": i.get("closed_at") if st == "published" else None,
                    "chars": len(text_of(i.get("body")))})
    out.sort(key=lambda d: d["created"], reverse=True)
    save_json("drafts.json", out[:200])
    print(f"초안 {len(out)}개 정리")


if __name__ == "__main__":
    main()
