# Next Fest / October 2026

두 게임의 데모 동접과 공식 공지·영상 이력을 같은 시간축에서 확인하는 공개 관측 페이지입니다.

- 대상: Hela: of Mice & Magic, Lethal Wedding
- 행사: 2026-10-20 02:00 ~ 2026-10-27 02:00 KST
- 최초 관측: 2026-10-20 15:59 KST. 그 이전 동접 이력은 확보하지 않았습니다.
- 공개 데이터 저장: JSON 및 CSV. 서버 DB와 API 키를 사용하지 않습니다.
- 호스팅: GitHub Pages. 사용자 컴퓨터가 꺼져 있어도 GitHub Actions가 실행됩니다.

## 수집과 한계

데모 AppID의 Steam `GetNumberOfCurrentPlayers` 응답을 20분 목표 주기로 기록합니다. GitHub 예약 작업은 지연되거나 누락될 수 있습니다. 차트에는 실제 관측 시각을 사용하며 관측하지 않은 피크를 추정하지 않습니다. Steam 연결이 끊긴 플레이어는 공식 API의 집계 범위에 포함되지 않습니다.

본편과 데모의 공식 Steam 공지는 3시간 목표 주기로 확인합니다. API에 표시된 공지 게시 시각을 저장하며, 해당 공지가 예고한 실제 행사의 발생 시각으로 바꾸지 않습니다. 새 공지의 원문 발췌는 자동 갱신하지만 의미 해석과 성장 원인 판정은 자동 작성하지 않습니다.

팔로워와 위시리스트는 미확보입니다. 공개 Community XML의 회원 수와 팔로워 의미를 확정할 수 없고 서로 다른 memberCount 값도 관측되어 팔로워로 사용하지 않습니다. 최초 검증한 공식 YouTube 영상 3개는 히스토리에 표시합니다. YouTube 전수 검색, 영상 조회수 시계열, 스트리머 실시간 시청자 수는 자동 수집 범위에 포함하지 않습니다.

수치는 자동 갱신되고 검토한 분석의 적용 구간·검토 시각은 보존됩니다. AI 모델이 상시 실행되는 서비스가 아닙니다. Astra가 설계·내용·검토를 맡고 GPT-6.1-SOL이 초기 출처를 확보했습니다.

## 종료

`2026-10-26T17:00:00Z` 이후 수집기는 외부 API를 호출하지 않습니다. 첫 종료 처리에서 아카이브를 저장하고 workflow 자체의 비활성화를 요청합니다. 이 요청이 실패하면 실행은 실패로 남고 다음 예약에서 재시도하지만 외부 수집은 계속 차단됩니다. 사이트는 설정된 종료 시각 이후 자체적으로 종료 상태를 표시합니다.

행사 종료 이후 관측은 계획하지 않았으므로 행사 후 유지율은 제공하지 않습니다. 최종 JSON·CSV와 페이지는 그대로 남습니다.

## 로컬 확인

```sh
python3 -m unittest discover -s tests -v
python3 scripts/validate.py
node --check site/app.js
python3 -m http.server 8765 --directory site
```

`python3 scripts/collect.py`는 현재 시각의 실제 공개 관측을 추가합니다. 운영 데이터로 테스트 수치를 만들지 않습니다.

## 자료 구조

| 경로 | 용도 |
| --- | --- |
| `config/manifest.json` | 행사 기간, 게임 식별자, 지표 정의, 참가 근거 |
| `site/data/config.json` | 사이트에서 읽는 설정 사본 |
| `site/data/observations.json` | 관측값·공식 이벤트·검토된 분석 |
| `site/data/observations.csv` | 내려받을 수 있는 관측 원본 |
| `docs/initial-evidence.json` | SOL이 확보한 최초 원천 대조 결과 |
| `docs/design.md` | 목적, 해석 기준과 검토 계약 |
| `.github/workflows/monitor.yml` | 수집·검증·기록·게시·종료 |

## 출처

- [Steam 행사 일정](https://partner.steamgames.com/doc/marketing/upcoming_events/nextfest/2026october)
- [동접 API](https://partner.steamgames.com/doc/webapi/ISteamUserStats#GetNumberOfCurrentPlayers)
- [공식 뉴스 API](https://partner.steamgames.com/doc/webapi/ISteamNews)
- [SteamDB 자동 수집 제한](https://steamdb.info/faq/)

게임명·이미지와 공지는 각 권리자의 자료이며, 이 프로젝트는 Valve 또는 각 개발사와 제휴하지 않은 공개 관측 기록입니다.
