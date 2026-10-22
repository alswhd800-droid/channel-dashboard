#!/usr/bin/env python3
"""인스타 계정 연결(2026-10-22, 메타 공식 'Instagram API with Instagram Login'). 계정마다 한 번만 하면 된다.

  python3 인스타_연결.py            → 인스타 '허용' 화면을 열고, 허용하면 토큰을 받아 저장
  python3 인스타_연결.py --no-open  → 주소만 출력(브라우저 에이전트가 사파리에서 열 때)
  python3 인스타_연결.py --refresh  → 저장된 토큰을 새로 연장(60일짜리, 7일 넘은 것만) — 맥 예약 작업이 하루 한 번 부른다

앱 정보는 ~/.channel-dashboard/ig_app.json {"app_id","app_secret"}(인스타 앱 ID·시크릿, 나만 읽기).
토큰은 ~/.channel-dashboard/ig_tokens.json 과 깃허브 비밀값 IG_OAUTH 에만 저장하고 화면에 찍지 않는다.
권한은 읽기 전용 두 가지(기본 정보·인사이트)라 게시물을 올리거나 바꿀 수 없다.
허용 뒤 인스타는 https 주소로만 돌려보내므로 대시보드의 ig-callback.html 이 이 맥(127.0.0.1:8766)으로 넘겨 준다.
"""
import http.server, json, os, secrets, shutil, subprocess, sys, time, urllib.error, urllib.parse, urllib.request

D = os.path.expanduser("~/.channel-dashboard")
APP, TOKENS = os.path.join(D, "ig_app.json"), os.path.join(D, "ig_tokens.json")
REDIRECT = "https://alswhd800-droid.github.io/channel-dashboard/ig-callback.html"
SCOPES = "instagram_business_basic,instagram_business_manage_insights"
REPO = "alswhd800-droid/channel-dashboard"
PORT = 8766
GRAPH = "https://graph.instagram.com"


def call(url, data=None):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode() if data else None, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:   # 메타 오류 문구만(토큰은 주소에 있어도 출력하지 않음)
        try:
            msg = json.load(e).get("error", {})
            msg = msg.get("message") if isinstance(msg, dict) else msg
        except ValueError:
            msg = ""
        sys.exit(f"메타 응답 오류 {e.code}: {msg}")


def save_and_push(allt):
    os.makedirs(D, exist_ok=True); os.chmod(D, 0o700)
    json.dump(allt, open(TOKENS, "w"), ensure_ascii=False, indent=1); os.chmod(TOKENS, 0o600)
    gh = shutil.which("gh") or "/opt/homebrew/bin/gh"
    val = json.dumps({"tokens": {v["username"]: v["token"] for v in allt.values()}})
    r = subprocess.run([gh, "secret", "set", "IG_OAUTH", "--repo", REPO], input=val, text=True, capture_output=True)
    return r.returncode == 0


def refresh():
    if not os.path.exists(TOKENS):
        return print("연결된 인스타 계정 없음")
    allt, changed = json.load(open(TOKENS)), False
    for uid, v in allt.items():
        if time.time() - v.get("refreshed", 0) < 7 * 86400:
            continue
        r = call(f"{GRAPH}/refresh_access_token?" + urllib.parse.urlencode({"grant_type": "ig_refresh_token", "access_token": v["token"]}))
        v.update(token=r["access_token"], refreshed=time.time(), expires=time.time() + int(r.get("expires_in", 0)))
        changed = True
        print(f"✔ @{v['username']} 토큰 연장")
    if changed:
        print("✔ 깃허브 비밀값 갱신" if save_and_push(allt) else "! 깃허브 비밀값 갱신 실패")


def main():
    if "--refresh" in sys.argv:
        return refresh()
    if not os.path.exists(APP):
        sys.exit("~/.channel-dashboard/ig_app.json 이 없어요(메타 개발자 앱의 인스타 앱 ID·시크릿). 먼저 앱을 만들어야 해요.")
    app = json.load(open(APP))
    state = secrets.token_urlsafe(16)
    url = "https://www.instagram.com/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": app["app_id"], "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPES, "state": state,
        "enable_fb_login": "0"})   # force_reauth 는 넣지 않는다 — 웹 세션이 끊겨 게시 자동화 계정이 로그아웃된다(10-22 몸리학)
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] != state:
                self.send_response(400); self.end_headers(); return
            got["code"] = q.get("code", [""])[0].split("#")[0]
            got["error"] = q.get("error_description", q.get("error", [""]))[0]
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers()
            self.wfile.write("<meta charset=utf-8><h3>연결 받았어요. 이 탭은 닫아도 돼요.</h3>".encode())

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", PORT), H)
    srv.timeout = 1
    print("인스타 '허용' 화면: 연결할 계정으로 로그인 → 허용", flush=True)
    if "--no-open" in sys.argv:
        print("URL: " + url, flush=True)
    else:
        subprocess.run(["open", url])
    end = time.time() + 900
    while time.time() < end and not got:
        srv.handle_request()
    if not got.get("code"):
        sys.exit(f"연결 안 됨: {got.get('error') or '15분 안에 허용을 누르지 않았어요'}")
    short = call("https://api.instagram.com/oauth/access_token", {
        "client_id": app["app_id"], "client_secret": app["app_secret"], "grant_type": "authorization_code",
        "redirect_uri": REDIRECT, "code": got["code"]})
    long = call(f"{GRAPH}/access_token?" + urllib.parse.urlencode({
        "grant_type": "ig_exchange_token", "client_secret": app["app_secret"], "access_token": short["access_token"]}))
    me = call(f"{GRAPH}/me?" + urllib.parse.urlencode({"fields": "user_id,username,account_type,followers_count", "access_token": long["access_token"]}))
    allt = json.load(open(TOKENS)) if os.path.exists(TOKENS) else {}
    allt[str(me["user_id"])] = {"username": me["username"], "token": long["access_token"], "account_type": me.get("account_type"),
                                "at": time.strftime("%Y-%m-%d %H:%M"), "refreshed": time.time(), "expires": time.time() + int(long.get("expires_in", 0))}
    ok = save_and_push(allt)
    print(f"✔ @{me['username']} 연결됨 ({me.get('account_type')}, 팔로워 {me.get('followers_count')}) — 지금 연결: "
          + ", ".join("@" + v["username"] for v in allt.values()))
    print("✔ 대시보드(깃허브)에도 반영" if ok else "! 깃허브 비밀값 갱신 실패 — 클로드에게 '인스타 비밀값 갱신' 요청")


if __name__ == "__main__":
    main()
