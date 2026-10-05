#!/usr/bin/env python3
"""유효 조회수용 채널 연결(2026-10-05). 채널마다 한 번만 하면 된다.

브라우저에 구글 '허용' 화면이 뜬다 → 그 채널 주인 구글 계정 선택(로그인) → 채널 선택
→ 'Google에서 확인하지 않은 앱'이면 [고급] → [채널 대시보드(으)로 이동] → 두 항목 모두 체크 → [계속].
연결 정보는 이 맥(~/.channel-dashboard/, 나만 읽기)과 깃허브 비밀값 YT_OAUTH 에만 저장하고 화면에 찍지 않는다.
권한은 읽기 전용 두 가지(유튜브 분석 보고서 보기·채널 이름 보기)라 채널을 바꿀 수 없다.
"""
import base64, hashlib, http.server, json, os, secrets, shutil, subprocess, sys, time, urllib.parse, urllib.request

D = os.path.expanduser("~/.channel-dashboard")
CLIENT, TOKENS = os.path.join(D, "oauth_client.json"), os.path.join(D, "yt_tokens.json")
SCOPES = "https://www.googleapis.com/auth/yt-analytics.readonly https://www.googleapis.com/auth/youtube.readonly"
REPO = "alswhd800-droid/channel-dashboard"
PORT = 8765


def post(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main():
    if not os.path.exists(CLIENT):
        sys.exit("~/.channel-dashboard/oauth_client.json 이 없어요(구글 클라우드 OAuth 클라이언트 정보). 먼저 만들어야 해요.")
    cl = json.load(open(CLIENT))
    redirect = f"http://127.0.0.1:{PORT}"
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cl["client_id"], "redirect_uri": redirect, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent select_account", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256"})
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] != state:
                self.send_response(400); self.end_headers(); return
            got["code"], got["error"] = q.get("code", [""])[0], q.get("error", [""])[0]
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write("<meta charset=utf-8><h3>연결 받았어요. 이 탭은 닫아도 돼요.</h3>".encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", PORT), H)
    srv.timeout = 1
    print("브라우저에서 구글 '허용' 화면을 열어요. 채널 주인 계정 → 채널 선택 → (확인 안 된 앱이면 고급 → 이동) → 두 항목 체크 → 계속")
    subprocess.run(["open", url])
    end = time.time() + 900
    while time.time() < end and not got:
        srv.handle_request()
    if not got.get("code"):
        sys.exit(f"연결 안 됨: {got.get('error') or '15분 안에 허용을 누르지 않았어요'}")
    t = post("https://oauth2.googleapis.com/token", {"client_id": cl["client_id"], "client_secret": cl["client_secret"], "code": got["code"],
                                                     "code_verifier": verifier, "grant_type": "authorization_code", "redirect_uri": redirect})
    req = urllib.request.Request("https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true", headers={"Authorization": "Bearer " + t["access_token"]})
    with urllib.request.urlopen(req, timeout=30) as r:
        items = json.load(r).get("items") or []
    if not items or not t.get("refresh_token"):
        sys.exit("이 계정에서 유튜브 채널을 찾지 못했어요. 채널 선택 화면에서 채널(브랜드 계정)을 골라 주세요.")
    cid, title = items[0]["id"], items[0]["snippet"]["title"]
    os.makedirs(D, exist_ok=True); os.chmod(D, 0o700)
    allt = json.load(open(TOKENS)) if os.path.exists(TOKENS) else {}
    allt[cid] = {"title": title, "refresh_token": t["refresh_token"], "scope": t.get("scope"), "at": time.strftime("%Y-%m-%d %H:%M")}
    json.dump(allt, open(TOKENS, "w"), ensure_ascii=False, indent=1); os.chmod(TOKENS, 0o600)
    print(f"✔ '{title}' 연결됨 (지금 연결된 채널: {', '.join(v['title'] for v in allt.values())})")
    gh = shutil.which("gh") or "/opt/homebrew/bin/gh"
    val = json.dumps({"client_id": cl["client_id"], "client_secret": cl["client_secret"], "tokens": {k: v["refresh_token"] for k, v in allt.items()}})
    r = subprocess.run([gh, "secret", "set", "YT_OAUTH", "--repo", REPO], input=val, text=True, capture_output=True)
    print("✔ 대시보드(깃허브)에도 반영 — 3시간 안에 숫자가 나와요" if r.returncode == 0 else "! 깃허브 비밀값 갱신 실패 — 클로드에게 '유효조회수 비밀값 갱신'을 요청하세요")


if __name__ == "__main__":
    main()
