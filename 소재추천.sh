#!/bin/bash
# 하루 2번(07·15시, ~/Library/LaunchAgents/com.minjong.sojae.plist) AI 소재 추천을 만들어 대시보드(🎯 소재 탭)에 올린다.
# 맥이 그 시각에 자고 있으면 깨어날 때 한 번 돈다. 기록은 같은 폴더의 소재추천.log
set -u
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
cd "$(dirname "$0")" || exit 1
LOG="소재추천.log"
say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }
[ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 600 ] && tail -300 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"

# 2026-10-12: 9/30 schedule.json 충돌이 풀리지 않은 채 남아 12일 동안 옛 코드로 돌고 올리기도 실패했다 → 남은 충돌은 버리고 원격에 맞춘다
# (이 사본에서 바꾸는 건 topics/ 결과뿐 — calibration·scored·history 는 보관했다가 되돌린다)
git rebase --abort 2>/dev/null; git merge --abort 2>/dev/null
if ! git pull --rebase --autostash -q 2>>"$LOG"; then
  say "! pull 실패 — 원격에 맞춤(topics 상태는 보존)"
  T=$(mktemp -d); cp topics/history.jsonl topics/calibration.json topics/scored.json "$T"/ 2>/dev/null
  git rebase --abort 2>/dev/null; git fetch -q origin && git reset -q --hard origin/main
  cp "$T"/* topics/ 2>/dev/null; rm -rf "$T"
fi
if ! /usr/bin/python3 소재추천.py >> "$LOG" 2>&1; then say "✘ 추천 실패"; exit 1; fi
git add topics/latest.json topics/history.jsonl
if git diff --cached --quiet; then say "바뀐 것 없음"; exit 0; fi
git -c user.name="dashboard-bot" -c user.email="dashboard-bot@users.noreply.github.com" \
    commit -q -m "소재 추천 $(date '+%Y-%m-%d %H:%M')" 2>>"$LOG"
if git pull --rebase --autostash -q 2>>"$LOG" && git push -q 2>>"$LOG"; then
  # 2026-09-29 사용자 "끝나면 바로 대시보드에 반영해줘" — 10분마다 도는 수집을 기다리지 않고 바로 한 번 돌린다
  if gh workflow run update.yml -R alswhd800-droid/channel-dashboard >/dev/null 2>>"$LOG"; then
    say "✔ 올림 · 대시보드 갱신 바로 요청(몇 분 안에 반영)"
  else
    say "✔ 올림 (갱신 요청 실패 — 다음 수집 때, 10분 안)"
  fi
else
  say "✘ 올리기 실패 — 다음 차례에 다시 시도"
fi
