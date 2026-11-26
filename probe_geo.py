import os, common
print("=== models visible to this key ===")
print(common.gemini_available())
print("=== candidate order ===")
cands = common.gemini_candidates()
print(cands)
print("=== per-model tiny request ===")
for m in cands[:12]:
    try:
        d, used = common.gemini({"contents": [{"parts": [{"text": "hi"}]}],
                                 "generationConfig": {"maxOutputTokens": 16}}, prefer=m)
        print(f"OK   {m} -> {' '.join(common.gemini_text(d).split())[:60]} usage={d.get('usageMetadata')}")
    except Exception as e:
        print(f"FAIL {m} -> {str(e)[:600]}")
