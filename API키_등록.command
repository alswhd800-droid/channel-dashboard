#!/bin/bash
# 유튜브 API 키 발급 도우미 — 더블클릭하면 발급 페이지를 열고, 받은 키를 안전하게 저장·확인합니다.
cd "$(dirname "$0")"
clear
echo "=============================================="
echo "  유튜브 API 키 발급 도우미 (무료, 약 5분)"
echo "=============================================="
echo
echo "브라우저에 구글 클라우드 페이지를 차례로 엽니다."
echo "자세한 순서는 같은 폴더의 'API키_발급방법.md'에도 있어요."
echo
read -p "① 엔터를 누르면 [프로젝트 만들기] 페이지가 열립니다. " _
open "https://console.cloud.google.com/projectcreate"
echo "   → 프로젝트 이름: channel-dashboard → [만들기]"
echo "     (처음이면 국가 선택·약관 동의 화면이 먼저 나와요. 결제 정보는 필요 없어요)"
echo
read -p "② 프로젝트가 만들어졌으면 엔터 → [YouTube Data API v3] 페이지가 열립니다. " _
open "https://console.cloud.google.com/apis/library/youtube.googleapis.com"
echo "   → 위쪽 프로젝트가 channel-dashboard 인지 확인 → 파란 [사용] 버튼"
echo
read -p "③ [사용]을 눌렀으면 엔터 → [사용자 인증 정보] 페이지가 열립니다. " _
open "https://console.cloud.google.com/apis/credentials"
echo "   → [+ 사용자 인증 정보 만들기] → [API 키]"
echo "   → 만들어진 키 옆 [복사]"
echo "   → (권장) 키 이름 클릭 → API 제한사항: [키 제한] → YouTube Data API v3 체크 → [저장]"
echo
echo "④ 복사한 키를 아래에 붙여넣고 엔터 (보안상 화면에 글자가 안 보여요)"
read -s -p "   API 키: " KEY
echo
KEY="$(echo "$KEY" | tr -d '[:space:]')"
if [ -z "$KEY" ]; then
  echo "   ✘ 키가 비어 있어요. 다시 실행해 주세요."
  read -p "엔터를 누르면 닫힙니다." _
  exit 1
fi

echo "   키 확인 중..."
CODE=$(curl -s -o /tmp/yt_key_check.json -w "%{http_code}" \
  "https://www.googleapis.com/youtube/v3/channels?part=id&forHandle=%40YouTube&key=$KEY")
if [ "$CODE" = "200" ]; then
  touch .env && chmod 600 .env
  grep -v '^YOUTUBE_API_KEY=' .env > .env.tmp 2>/dev/null; mv .env.tmp .env
  echo "YOUTUBE_API_KEY=$KEY" >> .env
  chmod 600 .env
  echo
  echo "   ✔ 성공! 키가 작동하고, 이 폴더의 .env 파일에 저장됐어요."
  echo "     (키는 채팅에 붙여넣지 마세요. 클로드에게 '키 등록했어'라고만 말하면 됩니다)"
else
  REASON=$(grep -o '"reason": *"[^"]*"' /tmp/yt_key_check.json | head -1)
  echo
  echo "   ✘ 키 확인 실패 (응답 $CODE $REASON)"
  echo "     - accessNotConfigured / 403: ②에서 YouTube Data API v3 [사용]을 안 눌렀거나 몇 분 기다려야 해요"
  echo "     - keyInvalid / 400: 키를 다시 복사해 주세요"
  echo "     저장하지 않았어요. 다시 실행해 주세요."
fi
rm -f /tmp/yt_key_check.json
echo
read -p "엔터를 누르면 닫힙니다." _
