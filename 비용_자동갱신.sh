#!/bin/bash
# 영상 1편 제작이 끝날 때 자동 실행(공통/영상폴더_정리.py의 cost_sync): 제작비를 다시 계산하고, 달라졌을 때만 대시보드에 올린다.
# 직접 실행해도 됨. 기록은 같은 폴더의 비용_자동갱신.log
set -u
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")" || exit 1
LOG="비용_자동갱신.log"
say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# 로그가 커지면 최근 200줄만 남김
[ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 400 ] && tail -200 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"

if ! /usr/bin/python3 "../공통/비용계산.py" >/dev/null 2>>"$LOG"; then
  say "✘ 계산 실패"; exit 1
fi
# 만든 편 목록(topics/done.json)도 함께 갱신 — 소재 추천 예약 실행(~/.sojae 사본)은 데스크톱 편 폴더를 못 읽어서
# 이 사본으로 '이미 만든 편'을 거른다. 전에는 갱신이 안 돼 만든 편이 추천에 다시 나올 수 있었다(2026-09-27).
/usr/bin/python3 소재추천.py --done-only >/dev/null 2>>"$LOG" || say "✘ 만든 편 목록 갱신 실패"
git diff --quiet -- topics/done.json; DONE_CHANGED=$?
# 실제 내용이 바뀐 경우만 올린다(시각·환율 갱신 줄만 다르면 넘어감)
CHANGED=$(git diff -U0 -- costs.json | grep -E '^[+-][^+-]' | grep -vE '"(생성|갱신)"' | head -1)
if [ -z "$CHANGED" ]; then
  git checkout -- costs.json 2>/dev/null
  [ "$DONE_CHANGED" -eq 0 ] && exit 0
fi
TOTAL=$(/usr/bin/python3 -c "import json;d=json.load(open('costs.json'));print(f\"{d['편수']}편 {d['합계krw']:,}원\")" 2>/dev/null)
git add costs.json topics/done.json
git -c user.name="dashboard-bot" -c user.email="dashboard-bot@users.noreply.github.com" \
    commit -q -m "제작비·만든 편 갱신 $(date '+%Y-%m-%d %H:%M')" 2>>"$LOG"
if git pull --rebase --autostash -q 2>>"$LOG" && git push -q 2>>"$LOG"; then
  say "✔ 올림 ($TOTAL)"
else
  say "✘ 올리기 실패 — 다음 차례에 다시 시도"
fi
