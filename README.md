# Tube Radar 설치 안내 (약 15분)

PC가 꺼져 있어도 GitHub가 **매일 자동으로** 유튜브를 스캔하고, 결과를 내 전용 웹사이트에 보여줍니다. 비용은 0원입니다.

- 매일 06시(한국): 전체 스캔 (키워드 검색 + 인기 차트 + 추적 채널 신규 영상)
- 12시 · 18시 · 00시: 추적 중인 영상·채널 수치만 갱신 (급상승 계산용)
- 하루 쿼터 사용량: 약 3,000~3,500 / 10,000 units

---

## 1단계. GitHub 가입

1. https://github.com/signup 에서 가입합니다. (이미 있으면 로그인)

## 2단계. 저장소 만들기

1. 오른쪽 위 **＋ → New repository**
2. Repository name: `tube-radar`
3. **Public** 선택 (무료로 웹사이트를 켜려면 Public 이어야 합니다. API 키는 비밀 금고에 넣으므로 노출되지 않습니다.)
4. **Create repository**

## 3단계. 파일 올리기

1. 만든 저장소 화면에서 **uploading an existing file** 링크를 누릅니다.
2. 압축을 푼 `tube-radar` 폴더 **안의 내용물 전부**(`.github` 폴더, `scripts` 폴더, `index.html`, `config.json`, `README.md`)를 끌어다 놓습니다.
3. 아래 **Commit changes** 클릭
4. 저장소 첫 화면에 `.github` 폴더가 보이는지 확인합니다.
   - 안 보이면: **Add file → Create new file** → 이름 칸에 `.github/workflows/scan.yml` 입력 → `scan.yml` 내용을 메모장으로 열어 복사·붙여넣기 → Commit

## 4단계. 유튜브 API 키 등록 (비밀 금고)

1. 저장소 **Settings → Secrets and variables → Actions**
2. **New repository secret**
3. Name: `YT_API_KEY` / Secret: 발급받은 YouTube API 키 붙여넣기 → **Add secret**

## 5단계. 웹사이트 켜기

1. **Settings → Pages**
2. Source(Build and deployment) 를 **GitHub Actions** 로 바꿉니다.

## 6단계. 첫 스캔 실행

1. 저장소 위쪽 **Actions** 탭 → (처음이면 초록 버튼 "I understand…enable" 클릭)
2. 왼쪽 **Tube Radar 스캔** → 오른쪽 **Run workflow** → mode `full` → **Run workflow**
3. 2~5분 뒤 초록 체크가 뜨면 완료
4. 사이트 주소: `https://내아이디.github.io/tube-radar/` (크롬 북마크 해두세요)

빨간 X가 뜨면 그 실행을 눌러 **유튜브 스캔** 단계 로그를 캡처해서 Claude에게 보여주세요.

---

## 바꾸고 싶을 때 (`config.json`)

저장소에서 `config.json` → 연필 아이콘으로 수정 → Commit 하면 다음 스캔부터 반영됩니다.

| 항목 | 뜻 |
|---|---|
| `keywords` | 탐색 키워드. 1개 추가 = 하루 200 units. 25개 정도까지 여유 있음 |
| `search_days` | 검색할 때 최근 며칠 업로드를 볼지 |
| `watch_channels` | 무조건 계속 추적할 채널 ID 목록 (사이트 찜 화면에서 복사 가능) |
| `rpm_krw` | 1,000회당 예상 수익(원). 넣으면 월 예상 수익 표시 |
| `daily_unit_budget` | 하루 최대 사용 units (기본 8,000) |

## 알아둘 점

- **급상승 수치는 이틀째부터 정확합니다.** 같은 영상을 두 번 이상 관측해야 증가 속도를 잴 수 있습니다.
- 유튜브 전체를 훑지는 못합니다. 키워드와 인기 차트로 찾은 채널을 계속 추적하는 방식이라 날이 갈수록 데이터가 풍부해집니다.
- 찜·메모는 보는 브라우저에 저장됩니다. 찜 화면의 **찜 백업**을 가끔 눌러 두세요.
- 데이터는 저장소의 `data` 브랜치에 최신본 1개만 보관됩니다.
- 사이트 주소는 공개 URL입니다(검색엔진 노출은 막아둠). 공개 유튜브 통계만 담겨 있어 민감한 정보는 없습니다.
