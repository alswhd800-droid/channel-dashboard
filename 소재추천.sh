#!/bin/bash
# 하루 2번(07·15시, ~/Library/LaunchAgents/com.minjong.sojae.plist) AI 소재 추천을 만들어 대시보드(🎯 소재 탭)에 올린다.
# 맥이 그 시각에 자고 있으면 깨어날 때 한 번 돈다. 기록은 같은 폴더의 소재추천.log
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")" || exit 1
LOG="소재추천.log"
say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
[ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 600 ] && tail -300 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"

git pull --rebase --autostash -q 2>>"$LOG"
if ! /usr/bin/python3 소재추천.py >> "$LOG" 2>&1; then say "✘ 추천 실패"; exit 1; fi
git add topics/latest.json topics/history.jsonl
if git diff --cached --quiet; then say "바뀐 것 없음"; exit 0; fi
git -c user.name="dashboard-bot" -c user.email="dashboard-bot@users.noreply.github.com" \
    commit -q -m "소재 추천 $(date '+%Y-%m-%d %H:%M')" 2>>"$LOG"
if git pull --rebase --autostash -q 2>>"$LOG" && git push -q 2>>"$LOG"; then
  say "✔ 올림 (대시보드 반영은 다음 수집 때, 10분 안)"
else
  say "✘ 올리기 실패 — 다음 차례에 다시 시도"
fi
