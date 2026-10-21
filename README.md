# Next Fest Monitor · October 2026

2026년 10월 Steam 넥페의 전체 공식 등록 목록에서 데모 동접 변화, 개발사의 공개 찜 발표와 관련 소식을 확인하는 분석 도구입니다.

- 공개 사이트: https://inh1095.github.io/nextfest-2026/
- 공식 등록 게임 7,164개, 데모 AppID 연결 7,163개. PegPegBall의 데모는 미확보입니다.
- 기준: 2026-10-20 공식 행사 등록 구성. US·KR 등록 집합은 같지만 국가별 검색 노출과 이용 가능 여부는 다릅니다.
- 행사: 2026-10-20 02:00 ~ 2026-10-27 02:00 KST.
- 원래 선택한 두 게임의 기록은 보존하며 나머지는 최초 실제 관측부터 기록합니다.
- JSON과 GitHub Pages를 사용합니다. 서버 DB·API 키·상시 실행 AI가 필요하지 않습니다.

## 화면

| 메뉴 | 용도 |
| --- | --- |
| 개요 | 목록·동접·비교 가능 범위와 최근 관측 증가 상위 10개 |
| 게임 비교 | 전체 목록 검색, 동접 비교, 공개 찜 발표가 있는 게임 검색 |
| 지표 분석 | 동접 차트·증가 구간·CSV, 찜 발표 이력·출처, 참고 계산·오차 확인 |
| 이벤트 히스토리 | 공식 공지·영상의 제목과 시각 검색, 사건 상세 |
| 수집 상태 | 게임별 정상·오류·대기·데모 미확보, 출처와 목표 주기 |

메뉴별 hash 주소, 직접 진입과 브라우저 뒤로 가기를 지원합니다. 목록은 25/50개씩 표시하고 상세 기록은 선택한 게임만 불러옵니다. 새로고침 버튼은 게시된 데이터를 다시 읽습니다. 관심 목록은 현재 브라우저에 저장되며 서버 수집 우선순위를 바꾸지 않습니다.

모바일·태블릿에서는 하단 메뉴와 카드형 목록을 사용합니다. 게임명·동접·증가량을 가로 스크롤 없이 확인하고, 보조 필터와 원자료·CSV는 펼쳐서 봅니다. 분석 화면은 차트 바로 아래에 선택 구간의 근거를 표시하며 모바일 증가 목록은 5개씩 제공합니다.

## 수집과 해석

GitHub Actions는 20분 간격으로 실행하도록 설정되어 있습니다. 사용자 컴퓨터와 독립적으로 실행되지만 GitHub 예약 작업은 지연되거나 누락될 수 있으므로 실제 실행 이력과 사이트 관측 시각으로 확인합니다.

초기 확인에서는 native `schedule` 실행 이력이 없어 Linux 사용자 timer를 통한 보조 감시도 제공합니다. `nextfest-monitor-watch.timer`는 PC와 해당 Linux 환경이 실행 중일 때 5분마다 GitHub만 확인하고, 실행 중인 작업이 없으며 최근 20분 동안 수집 발화가 없을 때 workflow를 실행합니다. 사이트를 열어 둘 필요는 없습니다. 이것이 PC가 꺼진 상태의 GitHub 예약 동작을 검증한 것은 아닙니다.

보조 감시는 지정된 개인 GitHub 계정의 자격증명을 프로세스 환경에서만 사용합니다. 인증·API 오류 시 실행하지 않고, 로컬 lock과 workflow의 15분 최소 간격 검사로 중복을 막습니다. 행사 종료 이후에는 외부 관측 없이 최종 archive를 요청하는 예외 1회만 허용하고, workflow 비활성화 확인 또는 종료 24시간 후 timer를 중단합니다. 설치 템플릿은 `ops/`에 있으며 실제 확인은 `systemctl --user status nextfest-monitor-watch.timer`로 합니다.

1회 실행에서 CCU 700회와 공식 공지 360회의 요청 예산을 배정합니다. 재시도도 예산에 포함합니다. 전체 데모 동접 순환 목표는 약 220분, 본편·데모 공지 순환 목표는 약 800분입니다. 기존 Hela와 Lethal Wedding은 동일 예산 안에서 매 실행 우선 확인합니다. 하루 예약 한도는 90,000회이며 작업이 중단되어도 예약분을 환급하지 않습니다. 이것은 프로젝트 한도이며 같은 IP/계정의 외부 사용량까지 보장하지 않습니다.

실제 완료 시각과 정상 응답값만 저장합니다. 실패·미확보는 null이며 정상 0과 구분합니다. 단일 관측은 기준선일 뿐 추세로 해석하지 않습니다. 관측 사이 오류가 있거나 게임별 목표 주기 × 2 + 30분을 넘으면 증가 구간으로 연결하지 않습니다. 관측 최고치는 실제 전체 피크와 다를 수 있습니다. 첫 관측 이전의 과거 시계열은 생성하지 않습니다.

공식 공지는 본편·데모 소스를 모두 확인해야 완료로 표시합니다. 한 소스만 조회한 경우 부분 확인이며 소식이 없다는 이유로 활동이 없었다고 판단하지 않습니다. API가 제공하는 최신 최대 20건의 공지를 조회하므로 전체 과거 공지 아카이브는 아닙니다. 공지 게시 시각과 실제 행사의 발생 시각을 구분합니다.

정확한 현재 찜 잔액과 신뢰할 수 있는 팔로워 수는 미확보입니다. Hela와 Lethal Wedding의 공식 앱 그룹 연결은 확인했지만 XML 안의 두 회원 수가 상충하여 대표값을 채택하지 않았습니다. 초기 검증된 공식 YouTube 영상 3개는 보존하지만 전체 게임의 영상 검색·조회수·스트리머 시청자 수는 자동 수집 범위에 포함하지 않습니다.

타사 전체 게임의 정확한 찜 수는 확인한 공개 경로에서 확보할 수 없습니다. GameDiscoverCo와 Raijin의 찜 수는 추정치이며 이 사이트에는 연결하지 않았습니다. 공개 문서 확인과 실제 데이터 검증을 구분한 출처 검토는 `docs/wishlist-source-audit.json`에 기록했습니다.

찜 화면은 `#/analysis?game=hela&range=all&metric=wishlists`, 공개 발표 검색은 `#/compare?view=wishlists`입니다. `config/wishlist-evidence.json`의 검토된 발표만 날짜·수치의 의미·플랫폼 범위·출처와 함께 표시합니다. 발표 당시의 도달 수치를 현재 잔액으로 표시하거나, 두 하한을 빼서 찜 증가량을 만들지 않습니다. Steam 전용인지 불명확한 발표는 플랫폼 미확인으로 표시합니다. 확인한 원문과 검토 범위는 `docs/wishlist-estimation-evidence.json`에 있습니다.

새로 수집된 공식 공지에서는 찜 관련 언급을 매번 자동으로 모읍니다. 이 목록은 미검토 소식이며 숫자를 자동 해석해 확정 발표에 편입하지 않습니다. 과거 발표를 잇는 가상의 일별 찜 차트나 팔로워 기반 자동 예측은 생성하지 않습니다.

접힌 참고 계산에서는 사용자가 직접 입력한 팔로워 수에 2023년 미출시 게임 조사에서 관측한 7–20배 범위를 적용할 수 있습니다. 이 범위는 당시 표본의 경험적 범위이며, 2026년 넥페의 예측구간·신뢰구간·정확도 보증이 아닙니다. 실제 잔액과 비교할 추정값의 게임·기준일이 같을 때 오차를 계산할 수 있습니다. 계산 입력은 브라우저 메모리에만 두며 URL·localStorage·서버로 전송하지 않습니다.

게시 전에 모든 게임의 기간별 요약을 관측 기록에서 다시 계산해 대조합니다. `scripts/evidence_guard.py`는 마지막 검증 성공 커밋을 보관하는 `evidence-approved` 브랜치와 비교해 기존 관측·공지·분석·찜 발표·팔로워 확인·참고 방법의 수정이나 삭제가 있으면 게시를 차단합니다. 검증 실패 후 다음 예약 실행에서도 같은 기준을 사용하며, 기준을 읽지 못하면 중단합니다. 검증을 통과한 데이터 커밋과 기준 브랜치는 하나의 atomic push로 갱신합니다. 새 관측과 수집 상태 갱신은 허용하지만 기존 기록의 값·시각·출처는 보존해야 합니다. 최신값과 최근 6/24시간 통계는 새 관측 및 기간 이동에 따라 달라집니다. 이 검사는 저장된 기록의 보존·계산 정합성을 확인하며 Steam 원천의 무오류나 미확보 찜 수의 정확성을 보장하지 않습니다.

목록 확보, 정상 관측, 공지 확인, 원인 검토는 별도 범위입니다. 수치 증가와 사건의 시간적 연관은 원인 입증이 아닙니다. 검토된 분석만 적용 구간·검토 시각과 함께 보관합니다. Astra가 설계·구현·검토를 맡고 GPT-6.1-SOL이 공식 목록·게임 식별자·최초 관측을 수집합니다. 이후 반복 수집은 Python과 Actions가 수행합니다.

## 종료

`2026-10-26T17:00:00Z` 이후 외부 API 호출을 차단합니다. 첫 종료 처리 시 아카이브를 저장하고 최종 게시가 성공한 뒤 workflow 비활성화를 요청합니다. 비활성화가 실패해 재실행되어도 외부 수집은 차단됩니다. 사이트와 기록은 남습니다. 행사 종료 후 유지율은 수집 범위가 아닙니다.

## 검증과 실행

```sh
python3 -m unittest discover -s tests -v
python3 scripts/validate.py
python3 scripts/evidence_guard.py --baseline-ref origin/evidence-approved
node --check site/app.js
python3 -m http.server 8765 --bind 127.0.0.1 --directory site
```

서버 실행 후 `python3 tests/browser_smoke.py`로 전체 목록·화면·필터·분석·오류·모바일을 검증합니다. 가상 데이터는 브라우저 메모리와 임시 테스트 폴더에만 사용합니다.

```sh
# 저장된 관측으로 인덱스만 재생성; 네트워크 호출 없음
python3 scripts/fleet.py --build-only
# 실제 관측 수집; 동시 실행하지 않음
python3 scripts/fleet.py --run-id unique-run-id
```

실행 전 예약 예산을 보존해야 합니다. Actions는 예약 상태를 원격에 먼저 커밋합니다. 중단된 실행의 ID를 재사용하지 않고 새 ID로 새 예산을 예약합니다. `scripts/collect.py`는 이전 두 게임용 코드와 회귀검증을 위해 보존하며 운영 실행에는 사용하지 않습니다.

## 자료 구조

| 경로 | 용도 |
| --- | --- |
| `config/manifest.json` | 행사·수집 예산·기존 우선 게임의 상세 근거 |
| `site/data/catalog.json` | 공식 등록 전체 게임의 식별자·태그·데모 연결·출처 |
| `site/data/summary.json` | 게임별 최신값·기간별 요약·수집 범위 |
| `site/data/events-index.json` | 전체 공개 사건 목록 |
| `config/wishlist-evidence.json` | 검토된 찜 발표·팔로워 충돌 기록·참고 방법 원본 |
| `site/data/wishlists.json` | 공개 찜 근거와 미검토 관련 공지 인덱스 |
| `site/data/games/{id}.json` | 게임별 관측·사건 본문·검토 기록 |
| `site/data/collection-state.json` | 공정 순환 위치·일별 요청 예약·실행 이력 |
| `site/data/observations.json`, `.csv` | 확장 이전 두 게임의 원본 기록 보존본 |
| `docs/catalog-evidence.json` | SOL의 공식 목록 대조·배치 조회 근거 |
| `docs/fleet-design.md` | 전체 게임 확장 설계·검토 기록 |
| `.github/workflows/monitor.yml` | 예약·수집·검증·게시·종료 |

## 출처

- [공식 넥페 행사 페이지](https://store.steampowered.com/sale/nextfest?cc=us&l=english)
- [Steam 행사 일정](https://partner.steamgames.com/doc/marketing/upcoming_events/nextfest/2026october)
- [동접 API](https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetNumberOfCurrentPlayers)
- [공식 뉴스 API](https://partner.steamgames.com/doc/webapi/ISteamNews)
- [Steam Web API 이용 조건](https://steamcommunity.com/dev/apiterms)

게임명·이미지와 공지는 각 권리자의 자료이며 이 프로젝트는 Valve 또는 각 개발사와 제휴하지 않은 공개 관측 기록입니다.
