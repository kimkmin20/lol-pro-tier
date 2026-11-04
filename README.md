# LoL Pro Tier

프로 LoL 경기로 만든 포지션별 티어표, 선수 단위 레이팅 승부 예측, 피어리스 모의 밴픽 도구.

- 사이트: GitHub Pages (`index.html`)
- 매일 06:17·14:17·22:17(한국 시간) GitHub Actions가 `scripts/update.py`를 실행해 새 경기(Oracle's Elixir·Leaguepedia), 챔피언 이름(Riot Data Dragon), 패치별 변경 챔피언(LoL Wiki)을 `data/`에 저장합니다. 페이지는 열 때 이 파일들을 읽어 레이팅과 티어를 다시 계산합니다.
- 기본 데이터: Oracle's Elixir 2014~2026 경기 기록.
- 조합 특성(AP/AD, 앞라인, 이니시, 스킬 포킹, 돌진, 보호, 하이퍼캐리): LoL Wiki 챔피언 분류와 Data Dragon 스킬 사거리로 계산(`scripts/champ_traits.py`). 새 챔피언·리워크도 자동 갱신 때 다시 계산함.
- 수동 실행: Actions 탭 → Daily data update → Run workflow.
