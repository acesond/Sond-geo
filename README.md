# Sond-geo — 핫딜방 AI 노출 자동화

사람들이 ChatGPT·Gemini·Perplexity·Claude에 핫딜 질문을 하면 **'10년차 가전매니저' / 시크릿 핫딜방**이 답에 나오도록 만드는 파이프라인입니다.

```
[이틀마다 자동]  1. 분석: 질문 12개 × AI 4개 → 내 브랜드 언급·인용 측정
                 2. 실행: 노출 약한 질문 → AI가 스레드·블로그 초안 → GitHub 이슈(검수대기)
[내가 폰으로]    3. 검수: 이슈 본문 고치고 '승인' 라벨
[자동]           4. 발행: 스레드는 즉시 자동 게시 / 블로그는 '수동발행' 안내
[언제든]         대시보드: https://acesond.github.io/Sond-geo/
```

## 처음 한 번 설정

### 1) GitHub Pages 켜기 (대시보드)
Settings → Pages → Source: **Deploy from a branch** → Branch: `main`, 폴더: `/docs` → Save

### 2) Actions 쓰기 권한
Settings → Actions → General → Workflow permissions → **Read and write permissions** → Save

### 3) API 키 넣기
Settings → Secrets and variables → Actions → New repository secret

| 이름 | 어디서 | 용도 |
|---|---|---|
| `OPENAI_API_KEY` | platform.openai.com → API keys | ChatGPT 측정 (+ 초안 예비) |
| `GEMINI_API_KEY` | aistudio.google.com → Get API key | Gemini 측정 + 초안 예비 |
| `PERPLEXITY_API_KEY` | perplexity.ai → Settings → API | Perplexity 측정 |
| `ANTHROPIC_API_KEY` | console.anthropic.com → API keys | Claude 측정 + **초안 작성** |
| `THREADS_ACCESS_TOKEN` | 아래 4) | 스레드 자동 게시 |
| `THREADS_USER_ID` | 아래 4) | 스레드 자동 게시 |

키는 있는 것만 넣어도 돌아갑니다(없는 AI는 건너뜀). 초안 작성은 ANTHROPIC → OPENAI → GEMINI 순서로 있는 키를 씁니다. Gemini 기본 모델은 `gemini-3.8-flash`이고, 구글이 모델을 단종하면 자동으로 살아있는 flash 모델로 바꿔 재시도합니다(`common.py`).
비용 감: 질문 12개 × AI 4개 = 회당 48번 호출, 이틀에 한 번 → 한 달 15회. 웹검색 호출 요금이 대부분이라 한 달 1~2만 원 안쪽 예상 (모델·요금제에 따라 다름).

### 4) 스레드 자동 게시 토큰 (everyday_hotdeal 계정)
1. developers.facebook.com → 앱 만들기 → 사용 사례에서 **Threads API 액세스** 선택
2. 권한: `threads_basic`, `threads_content_publish` 추가
3. 앱 역할 → 역할 → **Threads 테스터**로 everyday_hotdeal 추가 → 스레드 앱 설정 → 계정 → 웹사이트 권한 → 초대 수락
4. Threads API 탐색기(또는 '사용자 토큰 생성기')에서 토큰 발급 → **장기 토큰(60일)**으로 교환
5. `https://graph.threads.net/v1.0/me?fields=id,username&access_token=토큰` 을 열면 나오는 `id` 가 `THREADS_USER_ID`

> 장기 토큰은 60일마다 갱신해야 합니다. 브라우저에서
> `https://graph.threads.net/refresh_access_token?grant_type=th_refresh_token&access_token=지금토큰`
> 을 열어 나온 새 토큰으로 시크릿을 바꿔주세요. 만료되면 이슈에 '발행실패' 라벨과 안내 댓글이 달립니다.

### 5) 첫 실행
Actions → **geo-check** → Run workflow. 몇 분 뒤 대시보드에 결과가 뜨고, 노출 약한 질문은 이슈로 초안이 올라옵니다.

## 매일 쓰는 법 (폰 GitHub 앱)
1. **Issues** 탭 → `검수대기` 라벨 이슈 열기
2. `본문 시작`과 `본문 끝` 사이를 고침 (스레드는 500자 이하)
3. 라벨에 **승인** 추가 →
   - 스레드: 바로 게시되고 링크 댓글이 달린 뒤 자동으로 닫힘
   - 블로그: '수동발행'으로 바뀜 → 네이버 블로그에 직접 올리고 이슈 닫기
4. 마음에 안 드는 초안은 그냥 닫기

## 바꾸고 싶을 때
- 질문: `questions.txt` (한 줄에 하나)
- '언급'으로 칠 키워드: `brand.txt`
- 오픈톡 링크·채널·회당 초안 수: `config.json`
  - `openchat_link`에 오픈톡 링크를 넣으면 글에 참여 링크가 들어갑니다
  - `channels`: `["threads"]`만 두면 블로그 초안을 안 만듭니다
  - `max_drafts_per_run`: 회당 초안 개수 (기본 2)
- 측정 주기: `.github/workflows/geo-check.yml`의 cron
- 모델: Secrets/Variables 대신 워크플로 env에 `OPENAI_MODEL`, `GEMINI_MODEL`, `PERPLEXITY_MODEL`, `ANTHROPIC_MODEL`, `DRAFT_MODEL` 추가

## 알아둘 점
- 저장소가 공개면 이슈(초안)와 측정 결과도 공개입니다. API 키는 Secrets라 공개되지 않습니다.
- 쿠팡 링크가 들어간 글에는 대가성 고지 문구가 자동으로 붙습니다.
- AI 답변은 매번 조금씩 달라서 회차별 점유율이 흔들립니다. 몇 주 추이로 보세요.
