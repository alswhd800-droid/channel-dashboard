#!/bin/bash
# 텔레그램 알림 연결 도우미 — 급등·목표 달성·새 영상 성적·주간 리포트를 폰으로 받기
cd "$(dirname "$0")"
REPO="alswhd800-droid/channel-dashboard"
clear
echo "=============================================="
echo "  📱 텔레그램 알림 연결 (무료, 약 3분)"
echo "=============================================="
echo
echo "준비: 폰이나 맥에 텔레그램 앱이 설치·로그인되어 있어야 해요."
echo
read -p "① 엔터 → 텔레그램 'BotFather'가 열립니다. " _
open "https://t.me/BotFather"
echo "   → [시작] 누르고 /newbot 입력"
echo "   → 봇 이름 입력 (예: 채널알림)"
echo "   → 봇 아이디 입력 (영어, 끝이 bot 이어야 함. 예: minjong_channel_bot)"
echo "   → 'Use this token to access the HTTP API:' 아래 긴 글자(토큰)를 복사"
echo
echo "② 복사한 토큰을 붙여넣고 엔터 (보안상 글자가 안 보여요)"
read -s -p "   토큰: " TOKEN
echo
TOKEN="$(echo "$TOKEN" | tr -d '[:space:]')"
ME=$(curl -s "https://api.telegram.org/bot$TOKEN/getMe")
if ! echo "$ME" | grep -q '"ok":true'; then
  echo "   ✘ 토큰이 맞지 않아요. BotFather 메시지에서 토큰 전체를 다시 복사해 주세요."
  read -p "엔터를 누르면 닫힙니다." _; exit 1
fi
BOTNAME=$(echo "$ME" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin)['result']['username'])")
echo "   ✔ 봇 확인: @$BOTNAME"
echo
read -p "③ 엔터 → 내 봇 대화창이 열리면 [시작] 누르고 아무 말(예: 안녕) 보내기, 보낸 뒤 여기서 엔터 " _
open "https://t.me/$BOTNAME"
read -p "   메시지를 보냈으면 엔터 " _
CHAT=""
for i in 1 2 3 4 5 6; do
  CHAT=$(curl -s "https://api.telegram.org/bot$TOKEN/getUpdates" | /usr/bin/python3 -c "
import sys, json
d = json.load(sys.stdin)
ids = [u.get('message', {}).get('chat', {}).get('id') for u in d.get('result', []) if u.get('message')]
print(ids[-1] if ids else '')")
  [ -n "$CHAT" ] && break
  echo "   메시지를 기다리는 중... ($i)"; sleep 5
done
if [ -z "$CHAT" ]; then
  echo "   ✘ 메시지를 못 찾았어요. 봇 대화창에서 [시작] → '안녕'을 보낸 뒤 다시 실행해 주세요."
  read -p "엔터를 누르면 닫힙니다." _; exit 1
fi
curl -s -X POST "https://api.telegram.org/bot$TOKEN/sendMessage" -d chat_id="$CHAT" \
  --data-urlencode text="✅ 채널 대시보드 알림이 연결됐어요!
급등·목표 달성·새 영상 성적·주간 리포트가 여기로 와요.
📊 https://alswhd800-droid.github.io/channel-dashboard/" >/dev/null
echo "   ✔ 테스트 메시지를 보냈어요. 텔레그램을 확인해 보세요."
echo
echo "④ 깃허브 자동 수집에 연결하는 중..."
if printf '%s' "$TOKEN" | gh secret set TELEGRAM_BOT_TOKEN -R "$REPO" >/dev/null 2>&1 && printf '%s' "$CHAT" | gh secret set TELEGRAM_CHAT_ID -R "$REPO" >/dev/null 2>&1; then
  touch .env && chmod 600 .env
  grep -v '^TELEGRAM_' .env > .env.tmp 2>/dev/null; mv .env.tmp .env
  printf 'TELEGRAM_BOT_TOKEN=%s\nTELEGRAM_CHAT_ID=%s\n' "$TOKEN" "$CHAT" >> .env && chmod 600 .env
  echo "   ✔ 완료! 다음 수집(매시간)부터 알림이 폰으로 와요."
  echo "     (토큰은 채팅에 붙여넣지 마세요. 클로드에게는 '텔레그램 연결했어'라고만 말하면 돼요)"
else
  echo "   ✘ 깃허브 연결 실패 — 클로드에게 '텔레그램 깃허브 연결 실패'라고 알려주세요."
fi
echo
read -p "엔터를 누르면 닫힙니다." _
