#!/bin/bash
# 영상 제작비를 다시 계산해서 대시보드에 올립니다. (더블클릭)
cd "$(dirname "$0")"
clear
echo "=============================================="
echo "  💵 제작비 계산 → 대시보드 올리기"
echo "=============================================="
echo
/usr/bin/python3 "../공통/비용계산.py" || { echo "✘ 계산 실패"; read -p "엔터를 누르면 닫힙니다." _; exit 1; }
echo
if git diff --quiet -- costs.json 2>/dev/null; then
  echo "· 지난번과 같아서 올릴 내용이 없어요."
else
  git add costs.json
  git -c user.name="dashboard-bot" -c user.email="dashboard-bot@users.noreply.github.com" \
      commit -q -m "제작비 갱신 $(date '+%Y-%m-%d %H:%M')"
  git pull --rebase --autostash -q && git push -q && echo "✔ 올렸습니다. 다음 수집(10분 안)에 대시보드에 반영돼요."
  gh workflow run update.yml -R alswhd800-droid/channel-dashboard >/dev/null 2>&1 && echo "· 바로 반영되도록 수집도 한 번 돌렸어요(1~2분)."
fi
echo
echo "📊 https://alswhd800-droid.github.io/channel-dashboard/#cost"
read -p "엔터를 누르면 닫힙니다." _
