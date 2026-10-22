#!/usr/bin/env python3
"""유튜브 채널 대시보드 수집기.

1시간마다 실행: 채널·영상 공개 통계를 받아 data/에 쌓고, docs/index.html(대시보드)을 새로 만든다.
  python3 collect.py            # 수집 + 알림 + 대시보드 생성
  python3 collect.py --check    # 채널 찾기만 확인(핸들 → 채널 이름·구독자)
  python3 collect.py --build    # 수집 없이 저장된 데이터로 대시보드만 다시 생성
키: 환경변수 YOUTUBE_API_KEY 또는 같은 폴더 .env (값은 절대 출력하지 않음)
    텔레그램 알림(선택): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

- 쇼츠 구분: 3분 이하 영상만 youtube.com/shorts/ID 주소가 열리는지로 판별(결과 캐시)
- 광고 수익 조건 진행률(팬 후원 단계는 안 봄): 공개 API로 알 수 없는 시청 시간은 '본편 조회수 × 영상 길이 × 평균 시청 비율'로 추정
- 알림: 급등(1시간 조회수가 평소의 3배 이상·50회 이상), 새 영상, 24시간 성적, 구독자·조회수 목표, 수익 조건
- 새 영상 성적: 올린 뒤 6·24·48시간 조회수를 같은 채널·같은 종류(쇼츠/본편) 영상의 중간값과 비교
- 벤치마크: benchmarks.json 채널의 최근 영상을 6시간마다 확인
"""
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA, DOCS = ROOT / "data", ROOT / "docs"
KST = timezone(timedelta(hours=9))
API = "https://www.googleapis.com/youtube/v3/"
DASHBOARD_URL = "https://alswhd800-droid.github.io/channel-dashboard/"
TOPIC_ALERT_MIN = 80   # 🎯 소재 추천 알림 기준 점수
TOPIC_ALERT_TOP = 3    # 채널마다 점수 높은 몇 개만 알림(2026-09-27 추천이 채널당 20개로 늘어서 — 텔레그램 4,000자 넘지 않게)
RETENTION = 0.35              # 본편 평균 시청 비율 가정(시청 시간 추정용)
EARLY_HOURS = (6, 24, 48)     # 새 영상 성적 확인 시점
SURGE_MIN_PER_HOUR = 50       # 급등: 1시간 조회수 최소
SURGE_RATIO = 3               # 급등: 평소 시간당 조회수의 몇 배
BENCH_EVERY_HOURS = 6
SUBS_GOALS = (10, 50, 100, 300, 500, 1000, 5000, 10000, 50000, 100000)
VIDEO_GOALS = (1000, 10000, 100000, 1000000)
CHANNEL_GOALS = (10000, 100000, 1000000, 10000000)

# 유튜브 파트너 프로그램 광고 수익 조건(유튜브 고객센터 72851, 2026-09 확인)
#   구독자 1,000명 + (최근 12개월 공개 본편 시청 시간 4,000시간 또는 최근 90일 공개 쇼츠 조회수 1,000만 회)
# 2027-02-01부터 새로 신청하는 채널은 시청 시간 8,000시간 또는 쇼츠 2,000만 회(유튜브 블로그 2026-08-10)
ADS = {"subs": 1000, "watch": 4000, "shorts90": 10_000_000}
ADS_NEW = {"date": "2027-02-01", "watch": 8000, "shorts90": 20_000_000}

# 유효 조회수(2026-10-05 사용자 요청): 공개 API엔 없어서 유튜브 분석 API를 채널 주인 OAuth(읽기 전용)로 받는다.
#   깃허브는 비밀값 YT_OAUTH = {"client_id","client_secret","tokens":{채널ID: refresh_token}}, 맥은 ~/.channel-dashboard/ 파일.
#   분석 수치는 하루 한두 번만 바뀌어서 3시간마다만 받는다(무료, 할당량 여유).
ENGAGED_EVERY_HOURS = 3
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"


def env_value(name):
    val = os.environ.get(name, "").strip()
    env = ROOT / ".env"
    if not val and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                val = line.split("=", 1)[1].strip()
    return val


KEY = None


def get(method, **params):
    url = API + method + "?" + urllib.parse.urlencode({**params, "key": KEY})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if e.code >= 500 and attempt < 2:
                time.sleep(3)
                continue
            try:
                err = json.loads(body)["error"]
                reason = err.get("details", [{}])[0].get("reason") or err["errors"][0].get("reason")
                msg = f"{err.get('code')} {reason}: {err.get('message', '')[:200]}"
            except Exception:
                msg = f"{e.code}"
            raise SystemExit(f"유튜브 API 오류 ({method}) {msg}")  # 주소(키 포함)는 출력하지 않음
        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(3)
                continue
            raise


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def is_short(vid):
    """youtube.com/shorts/ID가 그대로 열리면(200) 쇼츠, 일반 영상 주소로 넘기면(303) 본편. 확인 실패 시 None"""
    req = urllib.request.Request(f"https://www.youtube.com/shorts/{vid}", method="HEAD",
                                 headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=15) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        return False if 300 <= e.code < 400 else None
    except Exception:
        return None


def seconds(iso):
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load(name, default):
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(name, obj):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def fmt(n):
    n = float(n)
    if abs(n) >= 1e8:
        return f"{n / 1e8:,.1f}".rstrip("0").rstrip(".") + "억"
    if abs(n) >= 1e4:
        return f"{n / 1e4:,.1f}".rstrip("0").rstrip(".") + "만"
    return f"{int(round(n)):,}"


def fetch_uploads(uploads, limit=None):
    ids, token = [], None
    while True:
        params = {"part": "contentDetails", "playlistId": uploads, "maxResults": 50}
        if token:
            params["pageToken"] = token
        try:
            r = get("playlistItems", **params)
        except SystemExit as e:
            if "playlistNotFound" in str(e):  # 영상이 하나도 없는 채널
                return ids
            raise
        ids += [it["contentDetails"]["videoId"] for it in r.get("items", [])]
        token = r.get("nextPageToken")
        if not token or (limit and len(ids) >= limit):
            return ids[:limit] if limit else ids


def video_record(v, name, old):
    dur = seconds(v["contentDetails"].get("duration"))
    short = old.get("short")
    if short is None:
        short = is_short(v["id"]) if dur <= 180 else False
        if short is None:
            short = None if dur > 60 else True  # 확인 실패: 다음 실행 때 다시 확인
    thumbs = v["snippet"].get("thumbnails", {})
    st = v.get("statistics", {})
    return {"ch": name, "title": v["snippet"]["title"], "published": v["snippet"]["publishedAt"], "dur": dur, "short": short,
            "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)), "comments": int(st.get("commentCount", 0)),
            "public": v.get("status", {}).get("privacyStatus", "public") == "public",
            "thumb": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")}


# ---------------------------------------------------------------- 수익 창출

def rate(hist, name, key, days=7):
    """최근 며칠 하루 평균 증가량(기록이 2일 이상 있을 때)"""
    ds = [d for d in sorted(hist["daily"]) if name in hist["daily"][d]][-(days + 1):]
    if len(ds) < 2:
        return None
    first, last = hist["daily"][ds[0]][name][key], hist["daily"][ds[-1]][name][key]
    span = (datetime.fromisoformat(ds[-1]) - datetime.fromisoformat(ds[0])).days or 1
    return (last - first) / span


def monetization(now, name, snap, mine, hist):
    """광고 수익 조건 하나만: 구독자(필수) + 본편 시청 시간 또는 쇼츠 조회수(둘 중 하나)"""
    in_days = lambda v, n: parse_time(v["published"]) >= now - timedelta(days=n)
    public = [v for v in mine if v.get("public", True)]
    shorts90 = sum(v["views"] for v in public if v["short"] and in_days(v, 90))
    longs = [v for v in public if not v["short"] and in_days(v, 365)]
    watch = sum(v["views"] * v["dur"] * RETENTION for v in longs) / 3600
    avg_long = (sum(v["dur"] for v in longs) / len(longs)) if longs else 0
    lr = rate(hist, name, "long_views")
    cur = {"subs": snap["subs"], "watch": round(watch, 1), "shorts90": shorts90}
    speed = {"subs": rate(hist, name, "subs"), "shorts90": rate(hist, name, "shorts_views"),
             "watch": (lr * avg_long * RETENTION / 3600) if lr is not None else None}
    window = {"subs": None, "watch": 365, "shorts90": 90}   # 기간 안에 채워야 하는 조건(오래된 것은 빠져나감)
    deadline = datetime.fromisoformat(ADS_NEW["date"]).replace(tzinfo=KST)
    days_left = max(0, (deadline - now).days)
    items = []
    for key, label, unit in (("subs", "구독자", "명"), ("watch", "본편 시청 시간 · 최근 12개월(추정)", "시간"),
                             ("shorts90", "쇼츠 조회수 · 최근 90일", "회")):
        goal, sp = ADS[key], speed[key]
        left = max(0, goal - cur[key])
        eta = None if left == 0 else (round(left / sp) if sp and sp > 0 else None)
        stuck = bool(window[key] and left and sp and sp > 0 and sp * window[key] < goal)  # 지금 속도로는 기간 안에 못 채움
        if key == "shorts90":
            need = goal / 90 if days_left >= 90 else (left / days_left if days_left else None)
        else:
            need = left / days_left if days_left else None
        items.append({"key": key, "label": label, "unit": unit, "cur": cur[key], "goal": goal,
                      "pct": min(100.0, cur[key] / goal * 100), "left": left, "eta": eta, "speed": sp,
                      "stuck": stuck, "need_per_day": None if left == 0 or need is None else round(need, 1)})
    by = {i["key"]: i for i in items}
    path = max(by["watch"]["pct"], by["shorts90"]["pct"])  # 시청 시간 또는 쇼츠 조회수 중 하나만 채우면 됨
    overall = min(by["subs"]["pct"], path)
    # 남은 시청 시간을 본편 조회수로 환산(영상 평균 길이 × 평균 시청 비율)
    views_left = round(by["watch"]["left"] * 3600 / (avg_long * RETENTION)) if avg_long else None
    ads = {"key": "ads", "name": "광고 수익", "items": items, "overall": overall, "done": overall >= 100,
           "best_path": "watch" if by["watch"]["pct"] >= by["shorts90"]["pct"] else "shorts90",
           "block": "subs" if by["subs"]["pct"] <= path else ("watch" if by["watch"]["pct"] >= by["shorts90"]["pct"] else "shorts90"),
           "avg_long": round(avg_long), "views_left": views_left}
    return {"tiers": [ads], "retention": RETENTION, "days_left": days_left, "new_rules": ADS_NEW}


# ---------------------------------------------------------------- 알림

def telegram(text):
    token, chat = env_value("TELEGRAM_BOT_TOKEN"), env_value("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False
    body = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"}).encode()
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", body, timeout=20) as r:
            return r.status == 200
    except Exception as e:
        print(f"! 텔레그램 전송 실패: {type(e).__name__}")  # 토큰이 든 주소는 출력하지 않음
        return False


def thin(points, now, keep_hours=3, key=lambda p: p[0]):
    """10분마다 쌓이는 기록 줄이기: 최근 3시간은 전부, 그보다 오래된 건 1시간에 1개만"""
    out, last = [], None
    for p in points:
        t = datetime.fromisoformat(key(p))
        if now - t <= timedelta(hours=keep_hours):
            out.append(p)
            continue
        hour = t.strftime("%Y%m%d%H")
        if hour != last:
            out.append(p)
            last = hour
    return out


def views_near(points, when, tolerance):
    """시각 when 이전의 가장 가까운 기록 (시각, 조회수). tolerance보다 멀면 None"""
    best = None
    for t, n in points:
        dt = datetime.fromisoformat(t)
        if dt <= when + timedelta(minutes=5) and (best is None or dt > best[0]):
            best = (dt, n)
    return best if best and when - best[0] <= tolerance else None


def median_early(early, videos, ch, short, hour, exclude):
    vals = [e[str(hour)][1] for vid, e in early.items()
            if vid != exclude and str(hour) in e and vid in videos and videos[vid]["ch"] == ch and bool(videos[vid]["short"]) == bool(short)]
    return statistics.median(vals) if vals else None


def rename_channels(channels, hist, money_hist, videos, alerts):
    """channels.json의 old_names(예전 표시 이름) 기록을 새 이름으로 옮긴다 — 채널 이름을 바꿔도 그래프·주간 기록이 이어진다.
    같은 채널을 두 이름으로 잠깐 같이 모은 때(2026-09-27 이유상자 = The Paradox Desk)는 새 이름 기록을 두고 옛 이름 쪽을 지운다(두 번 더해지지 않게)."""
    for entry in channels:
        new = entry["name"]
        for old in entry.get("old_names", []):
            for snap in list(hist["daily"].values()) + [h["ch"] for h in hist["hourly"]]:
                if old in snap:
                    snap.setdefault(new, snap.pop(old))
            for day in money_hist.values():
                if old in day:
                    day.setdefault(new, day.pop(old))
            for v in videos.values():
                if v.get("ch") == old:
                    v["ch"] = new
            for a in alerts["items"]:
                if a.get("ch") == old:
                    a["ch"] = new


# ---------------------------------------------------------------- 수집

# ---------------------------------------------------------------- 유효 조회수(유튜브 분석 API)
def engaged_auth():
    """유효 조회수용 OAuth 값. 없으면 None. 토큰·비밀값은 절대 출력하지 않는다"""
    raw = os.environ.get("YT_OAUTH", "").strip()
    if raw:
        try:
            return json.loads(raw)
        except ValueError:
            print("! YT_OAUTH 형식 오류 — 유효 조회수 건너뜀")
            return None
    d = Path.home() / ".channel-dashboard"
    try:
        cl = json.loads((d / "oauth_client.json").read_text(encoding="utf-8"))
        tok = json.loads((d / "yt_tokens.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {"client_id": cl["client_id"], "client_secret": cl["client_secret"], "tokens": {k: v["refresh_token"] for k, v in tok.items()}}


_ACCESS = {}


def access_tokens(auth):
    """채널ID → 분석 API 접근 토큰(1시간짜리, 한 번 실행 안에서 다시 씀)"""
    if _ACCESS:
        return _ACCESS
    for key, rt in (auth.get("tokens") or {}).items():
        try:
            req = urllib.request.Request("https://oauth2.googleapis.com/token", method="POST", data=urllib.parse.urlencode(
                {"client_id": auth["client_id"], "client_secret": auth["client_secret"], "refresh_token": rt, "grant_type": "refresh_token"}).encode())
            with urllib.request.urlopen(req, timeout=30) as r:
                _ACCESS[key] = json.load(r)["access_token"]
        except (urllib.error.URLError, KeyError, ValueError) as e:
            print(f"! 유튜브 분석 연결 하나 실패({getattr(e, 'code', type(e).__name__)}) — 만료됐으면 다시 연결 필요")
    return _ACCESS


def _analytics(token, cid, start, end, metrics, **extra):
    url = ANALYTICS_API + "?" + urllib.parse.urlencode({"ids": f"channel=={cid}", "startDate": start, "endDate": end, "metrics": metrics, **extra})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": "Bearer " + token}), timeout=60) as r:
        return json.load(r)


def collect_engaged(now, info):
    """영상별 유효 조회수(engagedViews)·분석 조회수(views)·평균 시청 비율·구독 증가·최근 7일 유효 조회수.
    채널마다 그 채널 토큰을 먼저 쓰고, 403이면 다른 토큰으로(관리자 권한이 있는 채널) 시도한다. 아무 토큰도 안 되면 '연결 안 됨'."""
    old = load("engaged.json", {})
    names = {c["name"] for c in info}
    if old.get("at") and now - datetime.fromisoformat(old["at"]) < timedelta(hours=ENGAGED_EVERY_HOURS) and names <= set(old.get("channels", {})):
        return
    auth = engaged_auth()
    if not auth:
        return
    access = access_tokens(auth)
    if not access:
        old.update(at=now.isoformat(timespec="minutes"), err="연결이 모두 만료됨 — 다시 연결 필요")
        save("engaged.json", old)
        return
    end, start7 = now.strftime("%Y-%m-%d"), (now - timedelta(days=7)).strftime("%Y-%m-%d")
    out = {"at": now.isoformat(timespec="minutes"), "err": None, "channels": {}, "videos": dict(old.get("videos") or {})}
    for c in info:
        res = {"ok": False, "err": "연결 안 됨"}
        for key in ([c["id"]] if c["id"] in access else []) + [k for k in access if k != c["id"]]:
            try:
                life = _analytics(access[key], c["id"], "2010-01-01", end, "engagedViews,views,averageViewPercentage,subscribersGained",
                                  dimensions="video", sort="-engagedViews", maxResults=200)
                week = _analytics(access[key], c["id"], start7, end, "engagedViews", dimensions="video", sort="-engagedViews", maxResults=200)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    continue
                res = {"ok": False, "err": f"분석 API 오류 {e.code}"}
                break
            except urllib.error.URLError as e:
                res = {"ok": False, "err": f"분석 API 연결 실패 {type(e).__name__}"}
                break
            w = {r[0]: r[1] for r in week.get("rows") or []}
            for vid, eng, views, avp, subs in life.get("rows") or []:
                out["videos"][vid] = {"eng": int(eng), "views": int(views), "avp": round(float(avp), 1), "subs": int(subs), "eng7": int(w.get(vid, 0))}
            res = {"ok": True, "err": None, "n": len(life.get("rows") or [])}
            break
        out["channels"][c["name"]] = res
    save("engaged.json", out)
    print("· 유효 조회수: " + ", ".join(f"{n} {str(r['n']) + '편' if r['ok'] else r['err']}" for n, r in out["channels"].items()))


# ---------------------------------------------------------------- 누가 보는지(유튜브 분석 API, 2026-10-22 개편)
AUDIENCE_EVERY_HOURS = 6


def collect_audience(now, info):
    """채널마다 시청자: 나이×성별(90일)·국가·유입 경로·검색어·기기·구독 여부·쇼츠/본편(28일) + 최근 90일 일별(조회·유효·시청 시간·구독 +/−·좋아요·공유)
    + 수익(파트너 채널, 수익 읽기 권한이 있을 때만). 분석 수치는 하루 한두 번 바뀌어서 6시간마다만 받는다."""
    old = load("audience.json", {})
    names = {c["name"] for c in info}
    if old.get("at") and now - datetime.fromisoformat(old["at"]) < timedelta(hours=AUDIENCE_EVERY_HOURS) and names <= set(old.get("channels", {})):
        return
    auth = engaged_auth()
    access = access_tokens(auth) if auth else {}
    if not access:
        return
    day = lambda n: (now - timedelta(days=n)).strftime("%Y-%m-%d")
    end, s28, s90 = now.strftime("%Y-%m-%d"), day(28), day(90)
    out = {"at": now.isoformat(timespec="minutes"), "channels": {}}
    for c in info:
        prev = (old.get("channels") or {}).get(c["name"]) or {}
        tok, res = None, {"ok": False, "err": "연결 안 됨"}
        for key in ([c["id"]] if c["id"] in access else []) + [k for k in access if k != c["id"]]:
            try:
                daily = _analytics(access[key], c["id"], s90, end, "views,engagedViews,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost,likes,shares",
                                   dimensions="day", sort="day")
                tok = access[key]
                break
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    continue
                res = {"ok": False, "err": f"분석 API 오류 {e.code}"}
                break
            except urllib.error.URLError as e:
                res = {"ok": False, "err": f"분석 API 연결 실패 {type(e).__name__}"}
                break
        if not tok:   # 잠깐 막힌 거면 지난 값은 두고 오류만 표시
            out["channels"][c["name"]] = {**prev, **res, **({"stale": True} if prev.get("ok") else {})}
            continue
        miss = []

        def q(start, metrics, **extra):
            try:
                return _analytics(tok, c["id"], start, end, metrics, **extra).get("rows") or []
            except urllib.error.HTTPError as e:
                miss.append(f"{extra.get('dimensions', metrics)} {e.code}")
            except urllib.error.URLError:
                miss.append(extra.get("dimensions", metrics))
            return None

        r = {"ok": True, "err": None, "daily": {"cols": ["day", "views", "engaged", "minutes", "avd", "gained", "lost", "likes", "shares"],
                                                "rows": [[x[0]] + [round(v) if isinstance(v, float) else v for v in x[1:]] for x in daily.get("rows") or []]}}
        rows = q(s90, "viewerPercentage", dimensions="ageGroup,gender", sort="ageGroup")
        r["age_gender"] = [[a, g, round(v, 1)] for a, g, v in rows] if rows else []
        rows = q(s28, "views,estimatedMinutesWatched", dimensions="country", sort="-views", maxResults=12)
        r["country"] = [[k, int(v), int(m)] for k, v, m in rows] if rows else []
        rows = q(s28, "views,estimatedMinutesWatched", dimensions="insightTrafficSourceType", sort="-views")
        r["traffic"] = [[k, int(v), int(m)] for k, v, m in rows] if rows else []
        rows = q(s28, "views", dimensions="insightTrafficSourceDetail", filters="insightTrafficSourceType==YT_SEARCH", sort="-views", maxResults=15)
        r["search"] = [[k, int(v)] for k, v in rows] if rows else []
        rows = q(s28, "views,estimatedMinutesWatched", dimensions="deviceType", sort="-views")
        r["device"] = [[k, int(v), int(m)] for k, v, m in rows] if rows else []
        rows = q(s28, "views,averageViewDuration", dimensions="subscribedStatus")
        r["subscribed"] = [[k, int(v), int(d)] for k, v, d in rows] if rows else []
        rows = q(s28, "views,estimatedMinutesWatched", dimensions="creatorContentType", sort="-views")
        r["content"] = [[k, int(v), int(m)] for k, v, m in rows] if rows else []
        try:   # 수익: 수익 읽기 권한(10-22 추가)으로 다시 연결한 파트너 채널만 — 403 은 '권한 없음'
            rows = _analytics(tok, c["id"], s90, end, "estimatedRevenue", dimensions="day", sort="day", currency="KRW").get("rows") or []
            r["revenue"] = [[d, round(v)] for d, v in rows]   # 원
        except urllib.error.HTTPError as e:
            r["revenue"] = None
            if e.code not in (401, 403):
                miss.append(f"수익 {e.code}")
        except urllib.error.URLError:
            r["revenue"] = prev.get("revenue")
        if miss:
            r["miss"] = miss
        out["channels"][c["name"]] = r
    save("audience.json", out)
    print("· 시청자 분석: " + ", ".join(f"{n} {'✔' if r.get('ok') else r.get('err')}" for n, r in out["channels"].items()))


# ---------------------------------------------------------------- 인스타(메타 공식 API, 2026-10-22)
#   인스타_연결.py 로 계정마다 한 번 허용 → 깃허브 비밀값 IG_OAUTH = {"tokens": {사용자이름: 60일 토큰}}(맥이 하루 한 번 연장), 맥은 ~/.channel-dashboard/ig_tokens.json
#   프로필(팔로워)은 매시간, 게시물 인사이트는 3시간, 일별 계정 인사이트는 하루치씩 채우고, 팔로워 나이·성별·지역은 하루 한 번.
IG_API = "https://graph.instagram.com/v23.0/"
IG_DAILY = "reach,views,accounts_engaged,total_interactions,likes,comments,shares,saves,profile_links_taps,follows_and_unfollows"


def insta_tokens():
    raw = os.environ.get("IG_OAUTH", "").strip()
    if raw:
        try:
            return json.loads(raw).get("tokens") or {}
        except ValueError:
            print("! IG_OAUTH 형식 오류 — 인스타 건너뜀")
            return {}
    try:
        tok = json.loads((Path.home() / ".channel-dashboard" / "ig_tokens.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {v["username"]: v["token"] for v in tok.values()}


class IgError(Exception):
    pass


def _ig(path, token, **params):
    url = IG_API + path + "?" + urllib.parse.urlencode({**params, "access_token": token})
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:   # 메타 오류 문구만(주소엔 토큰이 있어 출력하지 않음)
        try:
            err = json.load(e).get("error") or {}
            msg = f"{e.code} {err.get('code', '')} {str(err.get('message', ''))[:120]}"
        except ValueError:
            msg = str(e.code)
        raise IgError(msg) from None
    except urllib.error.URLError as e:
        raise IgError(type(e).__name__) from None


def _ig_values(res):
    """인사이트 응답 → {지표: 값}"""
    out = {}
    for it in res.get("data") or []:
        tv = it.get("total_value")
        if tv is not None:
            out[it["name"]] = tv.get("value")
        elif it.get("values"):
            out[it["name"]] = it["values"][-1].get("value")
    return out


def collect_insta(now):
    tokens = insta_tokens()
    if not tokens:
        return
    store = load("insta.json", {"accounts": {}})
    if store.get("at") and now - datetime.fromisoformat(store["at"]) < timedelta(minutes=50):
        return
    today = now.strftime("%Y-%m-%d")
    accts = store.setdefault("accounts", {})
    for user in [u for u in accts if u not in tokens]:   # 연결을 끊은 계정은 뺀다
        accts.pop(user)
    for user, tok in tokens.items():
        a = accts.setdefault(user, {})
        try:
            p = _ig("me", tok, fields="user_id,username,name,profile_picture_url,followers_count,follows_count,media_count,account_type,biography")
        except IgError as e:
            a["err"] = f"프로필 실패 {e}"
            print(f"! 인스타 @{user}: {a['err']}")
            continue
        a["err"] = None
        a["profile"] = {"username": p.get("username"), "name": p.get("name"), "pic": p.get("profile_picture_url"), "bio": (p.get("biography") or "")[:150],
                        "followers": p.get("followers_count", 0), "follows": p.get("follows_count", 0), "media": p.get("media_count", 0),
                        "type": p.get("account_type"), "url": f"https://www.instagram.com/{p.get('username')}/"}
        a.setdefault("hist", {})[today] = [p.get("followers_count", 0), p.get("media_count", 0)]
        a["hist"] = {d: v for d, v in a["hist"].items() if d >= (now - timedelta(days=400)).strftime("%Y-%m-%d")}
        a["hourly"] = thin([x for x in a.get("hourly", []) if x[0] >= (now - timedelta(days=14)).isoformat()] + [[now.isoformat(timespec="minutes"), p.get("followers_count", 0)]], now)
        # 게시물(최근 30개) + 게시물별 인사이트 — 3시간마다
        if not a.get("media_at") or now - datetime.fromisoformat(a["media_at"]) >= timedelta(hours=3):
            try:
                ms = _ig("me/media", tok, fields="id,caption,media_type,media_product_type,permalink,thumbnail_url,media_url,timestamp,like_count,comments_count", limit=30).get("data") or []
                old_m = {m["id"]: m for m in a.get("media", [])}
                media = []
                for m in ms:
                    reel = m.get("media_product_type") == "REELS"
                    rec = {"id": m["id"], "cap": (m.get("caption") or "").split("\n")[0][:90], "type": "릴스" if reel else ("여러 장" if m.get("media_type") == "CAROUSEL_ALBUM" else "사진" if m.get("media_type") == "IMAGE" else "영상"),
                           "url": m.get("permalink"), "thumb": m.get("thumbnail_url") or (m.get("media_url") if m.get("media_type") == "IMAGE" else None),
                           "t": parse_time(m["timestamp"].replace("+0000", "+00:00")).astimezone(KST).strftime("%Y-%m-%d %H:%M"),
                           "likes": m.get("like_count", 0), "comments": m.get("comments_count", 0)}
                    want = "reach,views,likes,comments,shares,saved,total_interactions" + (",ig_reels_avg_watch_time" if reel else "")
                    try:
                        v = _ig_values(_ig(f"{m['id']}/insights", tok, metric=want))
                    except IgError:
                        try:
                            v = _ig_values(_ig(f"{m['id']}/insights", tok, metric="reach,likes,comments,saved,shares"))
                        except IgError:
                            v = {k: old_m.get(m["id"], {}).get(k2) for k, k2 in (("reach", "reach"), ("views", "views"), ("shares", "shares"), ("saved", "saves"))}
                    rec.update(reach=v.get("reach"), views=v.get("views"), shares=v.get("shares"), saves=v.get("saved"), inter=v.get("total_interactions"),
                               avg_watch=round(v["ig_reels_avg_watch_time"] / 1000, 1) if v.get("ig_reels_avg_watch_time") else None)
                    vh = dict(old_m.get(m["id"], {}).get("vh") or {})   # 날짜별 조회수(어제 대비 증가용)
                    if rec["views"] is not None:
                        vh[today] = rec["views"]
                    rec["vh"] = {d: n for d, n in vh.items() if d >= (now - timedelta(days=30)).strftime("%Y-%m-%d")}
                    media.append(rec)
                a["media"], a["media_at"] = media, now.isoformat(timespec="minutes")
            except IgError as e:
                a["err"] = f"게시물 실패 {e}"
        # 일별 계정 인사이트: 빠진 날을 한 번에 최대 7일씩(처음엔 28일 채움)
        daily = a.setdefault("daily", {})
        todo = [(now - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(1, 29)]
        todo = [d for d in todo if d not in daily or (d >= (now - timedelta(days=2)).strftime("%Y-%m-%d") and daily[d].get("_at", "") < today)][:7]
        for d in todo:
            t0 = int(datetime.fromisoformat(d).replace(tzinfo=KST).timestamp())
            try:
                v = _ig_values(_ig("me/insights", tok, metric=IG_DAILY, period="day", metric_type="total_value", since=t0, until=t0 + 86400))
            except IgError as e:
                a["err"] = f"일별 인사이트 실패 {e}"
                break
            daily[d] = {**v, "_at": today}
        a["daily"] = {d: v for d, v in daily.items() if d >= (now - timedelta(days=120)).strftime("%Y-%m-%d")}
        # 팔로워·반응한 사람 나이·성별·나라·도시 — 하루 한 번(팔로워 100명 미만이면 메타가 주지 않음)
        if not a.get("demo_at") or now - datetime.fromisoformat(a["demo_at"]) >= timedelta(hours=24):
            demo, why = {}, None
            for metric, key in (("follower_demographics", "follower"), ("engaged_audience_demographics", "engaged")):
                for bd in ("age", "gender", "country", "city"):
                    res = None
                    for extra in ({"timeframe": "this_month"}, {}):
                        try:
                            res = _ig("me/insights", tok, metric=metric, period="lifetime", metric_type="total_value", breakdown=bd, **extra)
                            break
                        except IgError as e:
                            why = str(e)
                    if not res:
                        continue
                    for it in res.get("data") or []:
                        for b in (it.get("total_value") or {}).get("breakdowns") or []:
                            rows = sorted(([x["dimension_values"][0], x["value"]] for x in b.get("results") or []), key=lambda x: -x[1])
                            demo.setdefault(key, {})[bd] = rows[:12]
            a["demo"] = {**demo, "at": now.isoformat(timespec="minutes"), **({} if demo else {"why": why})}
            a["demo_at"] = now.isoformat(timespec="minutes")
        print(f"· 인스타 @{user}: 팔로워 {a['profile']['followers']:,}" + (f" ! {a['err']}" if a.get("err") else ""))
    store["at"] = now.isoformat(timespec="minutes")
    save("insta.json", store)


def collect():
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    channels = json.loads((ROOT / "channels.json").read_text(encoding="utf-8"))
    videos = load("videos.json", {})
    vhist = load("video_views.json", {})          # 영상 → {날짜: 조회수}
    vhour = load("video_hourly.json", {})         # 영상 → [[시각, 조회수]] 최근 8일
    early = load("video_early.json", {})          # 영상 → {"6": [나이(시간), 조회수], "24": …, "48": …}
    hist = load("history.json", {"hourly": [], "daily": {}})
    money_hist = load("money_hist.json", {})
    alerts = load("alerts.json", None)
    first_run = alerts is None
    alerts = alerts or {"items": [], "seen": []}
    rename_channels(channels, hist, money_hist, videos, alerts)
    seen = set(alerts["seen"])
    state = load("state.json", {})
    new_alerts = []
    quiet = set()   # 이번에 처음 들어온 채널(2026-10-05): 이미 있던 영상·지난 목표를 '새 영상'·'돌파' 알림으로 쏟아내지 않음

    def alert(kind, ch, title, detail="", url="", key=None):
        if key:
            if key in seen:
                return
            seen.add(key)
            if first_run:  # 처음 실행 때는 이미 지난 목표로 알림을 쏟아내지 않음
                return
        if ch in quiet:
            return
        item = {"t": now.isoformat(timespec="minutes"), "type": kind, "ch": ch, "title": title, "detail": detail, "url": url}
        alerts["items"].insert(0, item)
        new_alerts.append(item)

    snap, info = {}, []
    # 10-22: 채널 ID 가 있으면 ID 로 한 번에(핸들이 바뀌어도 안 빠지고, 채널 수만큼 쓰던 할당량이 1로)
    by_id, want = {}, [e["id"] for e in channels if e.get("id")]
    for k in range(0, len(want), 50):
        for it in get("channels", part="snippet,statistics,contentDetails", id=",".join(want[k:k + 50])).get("items", []):
            by_id[it["id"]] = it
    for entry in channels:
        ch = by_id.get(entry.get("id"))
        handle = ch["snippet"].get("customUrl") or (entry.get("handles") or [""])[0] if ch else None
        for h in ([] if ch else entry.get("handles", [])):
            r = get("channels", part="snippet,statistics,contentDetails", forHandle=h)
            if r.get("items"):
                handle, ch = h, r["items"][0]
                break
        if not ch:
            print(f"! {entry['name']}: 채널을 찾지 못함 ({entry.get('id') or ', '.join(entry['handles'])})")
            continue
        name, st = entry["name"], ch["statistics"]
        if not any(name in day for day in hist["daily"].values()):
            quiet.add(name)
            print(f"· {name}: 처음 수집하는 채널 — 이번엔 알림 없이 기록만")
        ids = fetch_uploads(ch["contentDetails"]["relatedPlaylists"]["uploads"])
        idset = set(ids)
        for k in range(0, len(ids), 50):
            for v in get("videos", part="snippet,contentDetails,statistics,status", id=",".join(ids[k:k + 50])).get("items", []):
                is_new = v["id"] not in videos
                rec = video_record(v, name, videos.get(v["id"], {}))
                videos[v["id"]] = rec
                vid = v["id"]
                url = f"https://www.youtube.com/{'shorts/' if rec['short'] else 'watch?v='}{vid}"
                kind = "쇼츠" if rec["short"] else "본편"
                vhist.setdefault(vid, {})[today] = rec["views"]
                pts = vhour.setdefault(vid, [])
                pts.append([now.isoformat(timespec="minutes"), rec["views"]])
                if is_new and not first_run:
                    alert("upload", name, f"새 {kind}{'가' if kind == '쇼츠' else '이'} 올라왔어요", rec["title"], url)
                # 급등: 약 1시간 전 기록 대비 시간당 조회수가 평소(그 전 24시간)의 3배 이상 (10분마다 수집)
                ref = views_near(pts[:-1], now - timedelta(hours=1), timedelta(minutes=40))
                if ref:
                    gap_h = (now - ref[0]).total_seconds() / 3600
                    if 0.5 <= gap_h <= 2:
                        per_h = (rec["views"] - ref[1]) / gap_h
                        base = views_near(pts[:-1], now - timedelta(hours=25), timedelta(hours=3))
                        base_h = None
                        if base:
                            span = (ref[0] - base[0]).total_seconds() / 3600
                            base_h = (ref[1] - base[1]) / span if span > 1 else None
                        recent = [a for a in alerts["items"] if a["type"] == "surge" and a["url"] == url
                                  and now - datetime.fromisoformat(a["t"]) < timedelta(hours=12)]
                        if per_h >= SURGE_MIN_PER_HOUR and (base_h is None or per_h >= SURGE_RATIO * max(base_h, 5)) and not recent:
                            times = f" (평소의 {per_h / max(base_h, 1):.1f}배)" if base_h else ""
                            alert("surge", name, f"{kind} 급등! 1시간에 +{fmt(per_h)}회{times}", rec["title"], url)
                # 새 영상 성적: 6·24·48시간 시점 조회수 기록
                age_h = (now - parse_time(rec["published"])).total_seconds() / 3600
                e = early.setdefault(vid, {})
                for hour in EARLY_HOURS:
                    if str(hour) not in e and hour <= age_h <= hour + 6:
                        e[str(hour)] = [round(age_h, 1), rec["views"]]
                        if hour == 24 and not first_run:
                            med = median_early(early, videos, name, rec["short"], 24, vid)
                            comp = f" · 이 채널 {kind} 평소의 {rec['views'] / med:.1f}배" if med else ""
                            alert("early", name, f"새 {kind} 24시간 성적: {fmt(rec['views'])}회{comp}", rec["title"], url)
                for goal in VIDEO_GOALS:
                    if rec["views"] >= goal:
                        alert("goal", name, f"{kind} 조회수 {fmt(goal)}회 돌파 🎉", rec["title"], url, key=f"video:{vid}:{goal}")
        for vid in [vid for vid, v in videos.items() if v["ch"] == name and vid not in idset]:
            videos.pop(vid)  # 채널에서 지워진 영상
        mine = [v for v in videos.values() if v["ch"] == name]
        snap[name] = {
            "subs": int(st.get("subscriberCount", 0)), "hidden": bool(st.get("hiddenSubscriberCount")),
            "views": int(st.get("viewCount", 0)), "videos": int(st.get("videoCount", 0)),
            "shorts_views": sum(v["views"] for v in mine if v["short"]), "long_views": sum(v["views"] for v in mine if not v["short"]),
            "shorts_count": sum(1 for v in mine if v["short"]), "long_count": sum(1 for v in mine if not v["short"]),
        }
        info.append({"name": name, "handle": handle, "id": ch["id"], "title": ch["snippet"]["title"],
                     "thumb": ch["snippet"]["thumbnails"].get("default", {}).get("url", "")})
        chan_url = f"https://www.youtube.com/channel/{ch['id']}"
        for goal in SUBS_GOALS:
            if snap[name]["subs"] >= goal:
                alert("goal", name, f"구독자 {fmt(goal)}명 돌파 🎉", "", chan_url, key=f"subs:{name}:{goal}")
        for goal in CHANNEL_GOALS:
            if max(snap[name]["views"], snap[name]["shorts_views"] + snap[name]["long_views"]) >= goal:
                alert("goal", name, f"채널 전체 조회수 {fmt(goal)}회 돌파 🎉", "", chan_url, key=f"chviews:{name}:{goal}")
    if not snap:
        sys.exit("수집된 채널이 없습니다")
    # channels.json 에서 뺀 채널의 영상은 지운다(영상·일정 화면에 남지 않게). 잠깐 못 찾은 채널은 목록에 있으니 그대로 둔다
    listed = {e["name"] for e in channels}
    for vid in [vid for vid, v in videos.items() if v["ch"] not in listed]:
        videos.pop(vid)

    hist["hourly"] = thin([h for h in hist["hourly"] if h["t"] >= (now - timedelta(days=14)).isoformat()] + [{"t": now.isoformat(), "ch": snap}],
                          now, key=lambda h: h["t"])
    hist["daily"][today] = snap
    money_today = {}
    for c in info:
        m = monetization(now, c["name"], snap[c["name"]], [v for v in videos.values() if v["ch"] == c["name"]], hist)
        money_today[c["name"]] = {t["key"]: round(t["overall"], 2) for t in m["tiers"]}
        for t in m["tiers"]:
            for p in (25, 50, 75):
                if t["key"] == "ads" and t["overall"] >= p:
                    alert("money", c["name"], f"광고 수익 조건 {p}% 달성", "수익창출 탭에서 남은 조건을 확인하세요", DASHBOARD_URL + "#money/" + urllib.parse.quote(c["name"]),
                          key=f"money:{c['name']}:ads:{p}")
            if t["done"]:
                alert("money", c["name"], "광고 수익 조건 달성! 🎉", "YouTube 스튜디오 → 수익 창출에서 신청하세요(2단계 인증·애드센스 필요)",
                      DASHBOARD_URL + "#money/" + urllib.parse.quote(c["name"]), key=f"money:{c['name']}:{t['key']}:done")
    money_hist[today] = money_today

    # 정리: 오래된 기록 줄이기
    cutoff = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    for vid in list(vhist):
        vhist[vid] = {d: n for d, n in vhist[vid].items() if d >= cutoff}
        if vid not in videos:
            vhist.pop(vid)
    hour_cut = (now - timedelta(days=8)).isoformat()
    vhour = {vid: thin([p for p in pts if p[0] >= hour_cut], now) for vid, pts in vhour.items() if vid in videos}
    early = {vid: e for vid, e in early.items() if vid in videos and e}
    money_hist = {d: v for d, v in money_hist.items() if d >= (now - timedelta(days=120)).strftime("%Y-%m-%d")}

    bench = collect_bench(now, state)
    try:
        collect_engaged(now, info)
    except Exception as e:   # 유효 조회수가 막혀도 대시보드는 그대로 만든다(메시지에 토큰이 섞이지 않게 종류만 출력)
        print(f"! 유효 조회수 실패: {type(e).__name__}")
    try:
        collect_audience(now, info)
    except Exception as e:
        print(f"! 시청자 분석 실패: {type(e).__name__}")
    try:
        collect_insta(now)
    except Exception as e:
        print(f"! 인스타 실패: {type(e).__name__}")

    # 주간 리포트: 월요일 오전 9시 이후 첫 실행에 한 번
    ctx = dict(now=now, info=info, videos=videos, vhist=vhist, hist=hist, early=early, money_hist=money_hist, alerts=alerts, bench=bench)
    data = build(ctx)
    if now.weekday() == 0 and now.hour >= 9 and state.get("weekly_sent") != today and data["weekly"]["days"] >= 2:
        w = data["weekly"]
        lines = [f"🗓️ 주간 리포트 (최근 {w['days']}일)", f"전체 조회수 +{fmt(w['total']['d_views'])} · 구독자 +{fmt(w['total']['d_subs'])}", ""]
        for c in w["channels"]:
            lines.append(f"• {c['name']}: 조회수 +{fmt(c['d_views'])} · 구독 +{fmt(c['d_subs'])}"
                         + (f" · 최고 '{c['best']['title'][:24]}' +{fmt(c['best']['gain'])}" if c.get("best") else ""))
        alert("weekly", "전체", f"주간 리포트: 조회수 +{fmt(w['total']['d_views'])} · 구독자 +{fmt(w['total']['d_subs'])}", "인사이트 → 주간 리포트에서 채널별로 보기", DASHBOARD_URL + "#insight/weekly")
        new_alerts[-1]["tg"] = "\n".join(lines)
        state["weekly_sent"] = today
        data = build(ctx)

    # 🎯 AI 소재 추천(맥 소재추천.py, 하루 2번): 새로 올라온 80점 이상 소재는 알림 + 텔레그램(2026-09-26 사용자 요청)
    for ch, cv in ((load_topics() or {}).get("channels") or {}).items():
        for t in sorted(cv.get("topics", []), key=lambda t: -(t.get("총점") or 0))[:TOPIC_ALERT_TOP]:
            if (t.get("총점") or 0) < TOPIC_ALERT_MIN:
                continue
            before = len(new_alerts)
            alert("topic", ch, f"소재 추천 {t['총점']}점: {t.get('소재')}", t.get("제목") or "", DASHBOARD_URL + "#topics",
                  key=f"topic|{ch}|{t.get('소재')}|{cv.get('at')}")
            if len(new_alerts) > before:
                new_alerts[-1]["tg"] = f"🎯 [{ch}] 소재 추천 {t['총점']}점\n{t.get('제목')}\n{(t.get('왜_터질까') or '')[:160]}"

    # ⏰ 업로드 주기(2026-09-27): 평소 간격보다 늦어지기 시작하면 채널마다 한 번. 이미 오래 쉬는 채널(늦어진 지 이틀 넘음)은 조용히.
    for r in data["cadence"]["rows"]:
        if r["late"] and r["n"] >= 3 and r["late_by"] <= 2:
            alert("cadence", r["name"], f"업로드가 늦어요: 마지막 업로드 {r['since']:.0f}일 전", f"평소 {r['target']:g}일마다 올렸어요 · 업로드 일정에서 확인",
                  DASHBOARD_URL + "#schedule", key=f"late|{r['name']}|{r['last']}")

    alerts["items"] = [a for a in alerts["items"] if a["t"] >= (now - timedelta(days=60)).isoformat()][:300]
    alerts["seen"] = sorted(seen)
    if new_alerts:
        msg = "\n\n".join(a.get("tg") or f"{a['title']}\n[{a['ch']}] {a['detail']}".rstrip() + (f"\n{a['url']}" if a["url"] else "") for a in reversed(new_alerts))
        if telegram(msg + f"\n\n📊 {DASHBOARD_URL}"):
            print(f"· 텔레그램 알림 {len(new_alerts)}건 전송")
    for a in alerts["items"]:
        a.pop("tg", None)

    save("videos.json", videos)
    save("video_views.json", vhist)
    save("video_hourly.json", vhour)
    save("video_early.json", early)
    save("history.json", hist)
    save("money_hist.json", money_hist)
    save("channels_info.json", info)
    save("alerts.json", alerts)
    save("state.json", state)
    write_page(data)
    print(f"✔ {data['updated']} 수집 완료 (새 알림 {len(new_alerts)}건): " + ", ".join(f"{c['name']} 구독 {c['subs']:,} · 조회 {c['views']:,}" for c in data["channels"]))


def collect_bench(now, state):
    bench = load("bench.json", {"at": None, "channels": [], "videos": {}})
    path = ROOT / "benchmarks.json"
    if not path.exists():
        return bench
    if bench.get("at") and now - datetime.fromisoformat(bench["at"]) < timedelta(hours=BENCH_EVERY_HOURS):
        return bench
    targets = json.loads(path.read_text(encoding="utf-8"))
    old = bench.get("videos", {})
    chans, vids = [], {}
    for b in targets:
        r = get("channels", part="snippet,statistics,contentDetails", forHandle=b["handle"])
        if not r.get("items"):
            print(f"! 벤치마크 {b['name']}: 채널을 찾지 못함")
            continue
        ch = r["items"][0]
        chans.append({"name": b["name"], "for": b.get("for", ""), "handle": b["handle"], "url": f"https://www.youtube.com/channel/{ch['id']}",
                      "thumb": ch["snippet"]["thumbnails"].get("default", {}).get("url", ""),
                      "subs": int(ch["statistics"].get("subscriberCount", 0)), "videos": int(ch["statistics"].get("videoCount", 0))})
        ids = fetch_uploads(ch["contentDetails"]["relatedPlaylists"]["uploads"], limit=50)
        for k in range(0, len(ids), 50):
            for v in get("videos", part="snippet,contentDetails,statistics", id=",".join(ids[k:k + 50])).get("items", []):
                if parse_time(v["snippet"]["publishedAt"]) < now - timedelta(days=30):
                    continue
                vids[v["id"]] = video_record(v, b["name"], old.get(v["id"], {}))
    bench = {"at": now.isoformat(timespec="minutes"), "channels": chans, "videos": vids}
    save("bench.json", bench)
    return bench


# ---------------------------------------------------------------- 대시보드 데이터

def load_costs(chans):
    """맥에서 만든 costs.json(영상 1편당 제작비). 없으면 None — 대시보드는 안내만 띄운다.
    유튜브 채널 조회수와 이름으로 짝지어 '조회수 1,000회당 제작비'까지 계산한다."""
    p = ROOT / "costs.json"
    if not p.exists():
        return None
    try:
        c = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    import unicodedata
    nfc = lambda x: unicodedata.normalize("NFC", x)
    views = {nfc(x["name"]): (x["shorts_views"] + x["long_views"]) for x in chans}
    for ch in c.get("채널", []):
        ch["name"] = nfc(ch["name"])
        v = views.get(ch["name"])
        ch["조회수"] = v
        ch["천회당krw"] = round(ch["합계krw"] / v * 1000) if v else None
    c["집계일"] = c.get("생성")
    return c


def load_outliers():
    """발굴.py가 만든 outliers.json(떡상 후보). 없으면 None — 대시보드는 안내만 띄운다."""
    p = DATA / "outliers.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_topics():
    """소재추천.py(맥, 하루 2번)가 main 브랜치 topics/latest.json 에 쓴 AI 소재 추천. 없으면 None.
    지난 추천(채널별 최근 6번, 이번 것 제외)도 같이 싣는다 — 새 추천으로 바뀌어도 좋은 소재를 다시 볼 수 있게(2026-09-27)."""
    p = ROOT / "topics" / "latest.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    hist, hp = {}, ROOT / "topics" / "history.jsonl"
    if hp.exists():
        for line in hp.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            hist.setdefault(r.get("channel"), []).append({"at": r.get("at"), "topics": [
                {k: t.get(k) for k in ("소재", "제목", "총점", "최신", "갈래") if t.get(k) is not None} for t in r.get("topics", [])]})
        for ch in list(hist):
            cur = ((d.get("channels") or {}).get(ch) or {}).get("at")
            hist[ch] = [h for h in hist[ch] if h["at"] != cur][-6:][::-1]
    d["history"] = hist
    return d


# ---------------------------------------------------------------- 제작 현황 · 채널 효율 · 업로드 주기 (2026-09-27 사용자: 대시보드 아이디어 1·2·3)

MATCH_STOP = {"어떻게", "이유", "했을까", "까지", "그리고", "지금", "우리", "shorts", "하는", "있는", "없는", "무엇", "누가", "정말",
              "the", "and", "why", "how", "what", "its", "with"}


def _mtoks(s):
    return {w for w in re.findall(r"[가-힣a-z0-9]{2,}", (s or "").lower()) if w not in MATCH_STOP}


def _mnorm(s):
    return re.sub(r"[\W_]+", "", (s or "").lower())


def topic_match(p, text):
    """고른 소재 ↔ 편 폴더 이름·영상 제목: 핵심 대상 이름이 들어 있거나, 소재·제목 낱말이 2개 이상 겹치면 같은 편으로 본다."""
    t = _mnorm(p.get("대상"))
    if len(t) >= 2 and t in _mnorm(text):
        return True
    return len(_mtoks(f"{p.get('소재') or ''} {p.get('제목') or ''}") & _mtoks(text)) >= 2


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default


def views_on_day(vv, published, days=3):
    """올린 뒤 days 일째 조회수(일별 기록). 기록이 올린 날 뒤에 시작했거나 아직 days 일이 안 됐으면 None."""
    if not vv:
        return None
    pub = parse_time(published).astimezone(KST)
    if min(vv) > pub.strftime("%Y-%m-%d"):
        return None
    later = sorted(d for d in vv if d >= (pub + timedelta(days=days)).strftime("%Y-%m-%d"))
    return vv[later[0]] if later else None


def median3(videos, vhist, now):
    """채널·종류(쇼츠 s / 본편 l)별 '올린 뒤 3일 조회수' 중앙값 — 최근 60일 영상 3편 이상일 때."""
    groups = {}
    for vid, v in videos.items():
        if (now - parse_time(v["published"])).days > 60:
            continue
        x = views_on_day(vhist.get(vid), v["published"])
        if x is not None:
            groups.setdefault(f"{v['ch']}|{'s' if v['short'] else 'l'}", []).append(x)
    return {k: statistics.median(xs) for k, xs in groups.items() if len(xs) >= 3}


def pipeline(videos, vhist, med3, topics, now):
    """만들기로 한 소재(topics/picks.json, 맥에서 `소재추천.py --pick`)의 지금 상태:
    만들기로 함 → 제작 중(고른 뒤 새 편 폴더가 생김, 폴더 목록은 맥이 올리는 topics/done.json) → 업로드(채널에 올라감 + 3일 조회수).
    추천 적중 = 소재추천.py 가 맞춰 둔 hits(추천 뒤에 올라온, 추천과 제목이 겹치는 우리 영상)."""
    picks = read_json(ROOT / "topics" / "picks.json", {"items": []})
    done = read_json(ROOT / "topics" / "done.json", {})

    def vinfo(vid):
        v = videos[vid]
        v3 = views_on_day(vhist.get(vid), v["published"])
        base = med3.get(f"{v['ch']}|{'s' if v['short'] else 'l'}")
        return {"id": vid, "title": v["title"], "short": bool(v["short"]), "views": v["views"], "thumb": v.get("thumb", ""),
                "published": parse_time(v["published"]).astimezone(KST).strftime("%Y-%m-%d"),
                "age": round((now - parse_time(v["published"])).total_seconds() / 86400, 1),
                "v3": v3, "base": base, "ratio": round(v3 / base, 2) if v3 and base else None,
                "url": f"https://www.youtube.com/{'shorts/' if v['short'] else 'watch?v='}{vid}"}

    items = []
    for p in picks.get("items", []):
        ch = p.get("ch")
        try:
            picked = datetime.fromisoformat(str(p.get("picked_at")).replace(" ", "T")).replace(tzinfo=KST)
        except Exception:
            picked = now
        folder = p.get("folder")
        if not folder:
            known = set(p.get("known_folders") or [])
            folder = next((f for f in done.get(ch, []) if f not in known and topic_match(p, f)), None)
        vid = p.get("video") if p.get("video") in videos else None
        if not vid:
            cands = sorted((parse_time(v["published"]), k) for k, v in videos.items()
                           if v["ch"] == ch and parse_time(v["published"]) >= picked - timedelta(days=1) and topic_match(p, v["title"]))
            vid = cands[0][1] if cands else None
        row = {k: p.get(k) for k in ("id", "ch", "picked_at", "rec_at", "rank", "소재", "제목", "대상", "총점", "최신")}
        row.update(folder=folder, status="upload" if vid else ("making" if folder else "picked"), video=vinfo(vid) if vid else None)
        items.append(row)
    hits = []
    for ch, cv in ((topics or {}).get("channels") or {}).items():
        for h in ((cv.get("calib") or {}).get("hits") or []):
            vid = re.split(r"[/=]", h.get("url") or "")[-1]
            if vid in videos:
                hits.append({"ch": ch, "소재": h.get("소재"), "추천점수": h.get("추천점수"), "추천시각": h.get("추천시각"), "video": vinfo(vid)})
    hits.sort(key=lambda h: h["video"]["published"], reverse=True)
    rs = [h["video"]["ratio"] for h in hits if h["video"]["ratio"]]
    return {"items": items, "hits": hits[:30], "hit_n": len(hits), "hit_ratio": round(statistics.median(rs), 2) if rs else None,
            "counts": {s: sum(1 for x in items if x["status"] == s) for s in ("picked", "making", "upload")}}


def efficiency(chans, vids, hist, costs, weekly, now):
    """채널 효율판: 최근 30일 새 영상 1편당 평균 조회(쇼츠·본편 따로도), 7일 조회 증가와 지난주 대비, 1천 회당 구독, 1천 회당 제작비.
    '이번 주 집중할 채널' = 최근 30일에 2편 이상 올린 채널 중 편당 조회 1위(같으면 7일 증가율이 큰 쪽)."""
    days = sorted(hist["daily"])
    if not days:
        return {"rows": [], "focus": None}

    def snap(back):
        c = [d for d in days if d <= (now - timedelta(days=back)).strftime("%Y-%m-%d")]
        return hist["daily"][c[-1]] if c else None
    s0, s7, s14 = hist["daily"][days[-1]], snap(7), snap(14)
    cost = {c["name"]: c for c in ((costs or {}).get("채널") or [])}
    wk = {c["name"]: c for c in (weekly.get("channels") or [])}
    avg = lambda xs: round(sum(xs) / len(xs)) if xs else None
    rows = []
    for c in chans:
        n = c["name"]
        rec = [x for x in vids if x["ch"] == n and x["age"] <= 30]
        v = lambda s: ((s or {}).get(n) or {}).get("views")
        w7 = v(s0) - v(s7) if v(s0) is not None and v(s7) is not None else None
        p7 = v(s7) - v(s14) if v(s7) is not None and v(s14) is not None else None
        cc = cost.get(n) or {}
        best = max(rec, key=lambda x: x["views"], default=None)
        rows.append({"name": n, "uploads30": len(rec), "uploads14": sum(1 for x in rec if x["age"] <= 14),
                     "per_ep": avg([x["views"] for x in rec]),
                     "per_ep_s": avg([x["views"] for x in rec if x["short"]]), "per_ep_l": avg([x["views"] for x in rec if not x["short"]]),
                     "w7": w7, "p7": p7, "growth": round((w7 - p7) / p7 * 100) if w7 is not None and p7 else None,
                     "subs_per_1k": (wk.get(n) or {}).get("subs_per_1k"),
                     "cost_per_1k": cc.get("천회당krw"), "cost_per_ep": round(cc["합계krw"] / cc["편수"]) if cc.get("편수") else None,
                     "ads": next((t["overall"] for t in c["money"]["tiers"] if t["key"] == "ads"), None),
                     "best": {k: best[k] for k in ("title", "url", "views", "short")} if best else None})
    rows.sort(key=lambda r: -(r["per_ep"] or -1))
    cand = [r for r in rows if r["uploads30"] >= 2 and r["per_ep"]]
    focus = None
    if cand:
        top = max(cand, key=lambda r: (r["per_ep"], r["growth"] or 0))
        why = [f"최근 30일 새 영상 1편당 평균 {fmt(top['per_ep'])}회로 {len(cand)}개 채널 중 1위"]
        if top["w7"] is not None:
            why.append(f"최근 7일 조회 +{fmt(top['w7'])}" + (f"(지난주보다 {top['growth']:+d}%)" if top["growth"] is not None else ""))
        if top["cost_per_1k"]:
            why.append(f"조회 1천 회당 제작비 {top['cost_per_1k']:,}원")
        if top["subs_per_1k"] is not None:
            why.append(f"1천 회당 구독 {top['subs_per_1k']}명")
        second = next((r["name"] for r in sorted(cand, key=lambda r: (-r["per_ep"], -(r["growth"] or 0))) if r["name"] != top["name"]), None)
        focus = {"name": top["name"], "why": why, "next": second}
    return {"rows": rows, "focus": focus}


def schedule(videos, now):
    """📅 업로드 일정(2026-09-28): 일정.py(맥)가 편 폴더 업로드 기록에서 모은 schedule.json 중 아직 공개로 안 잡힌 것.
    예약 영상은 비공개라 API 키로는 안 보여서 기록을 쓴다. 공개된 영상은 화면이 videos 에서 바로 그린다.
    st: 예약(ID 있음·시각 전) · 공개중(시각이 막 지남 — 다음 수집 때 잡힘) · 계획(ID 없음 = 기록상 아직 안 올림) · 확인(시각이 지났는데 공개로 안 잡힘)"""
    S = read_json(ROOT / "schedule.json", {})
    pub = {}
    for v in videos.values():
        if v.get("public", True):
            pub.setdefault((v["ch"], bool(v["short"])), []).append(parse_time(v["published"]))
    items = []
    for x in S.get("items") or []:
        try:
            t = datetime.strptime(x["t"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)
        except (KeyError, ValueError):
            continue
        v = videos.get(x.get("id") or "")
        if v and v.get("public", True):
            continue                                   # 공개됨 → videos 쪽에 있다
        if not x.get("id") and any(abs((p - t).total_seconds()) <= 900 for p in pub.get((x["ch"], x.get("kind") == "쇼츠"), [])):
            continue                                   # 계획한 시각에 같은 종류 영상이 공개됨
        gone = (now - t).total_seconds() / 60
        if gone > 3 * 1440:
            continue                                   # 사흘 넘게 확인 안 된 기록은 접는다
        st = ("예약" if x.get("id") else "계획") if gone < 0 else "공개중" if x.get("id") and gone <= 40 else "확인"
        items.append({"ch": x["ch"], "t": x["t"], "kind": x.get("kind", "본편"), "ep": x.get("ep", ""), "id": x.get("id", ""), "st": st})
    items.sort(key=lambda x: (x["t"], x["ch"]))
    return {"at": S.get("at"), "items": items}


def cadence(videos, now, sched=None):
    """업로드 주기: 채널마다 평소 간격(올린 날짜끼리 최근 10번 간격의 중앙값 — channels.json 의 every_days 가 있으면 그 값),
    마지막 업로드, 늦어짐(평소의 1.5배 + 반나절을 넘김 — 공개 예약이 걸려 있으면 늦음 아님), 최근 28일 달력(날마다 [쇼츠, 본편] 편수),
    예약(next 가장 빠른 공개 예약 · until 가장 늦은 예약 · booked 개수)."""
    cfg = [e for e in read_json(ROOT / "channels.json", []) if e.get("name")]
    booked = {}
    for x in (sched or {}).get("items") or []:
        if x["st"] in ("예약", "공개중"):
            booked.setdefault(x["ch"], []).append(x["t"])
    dates = [(now - timedelta(days=27 - i)).astimezone(KST).strftime("%Y-%m-%d") for i in range(28)]
    by = {}
    for v in videos.values():
        if v.get("public", True):
            by.setdefault(v["ch"], []).append((parse_time(v["published"]), bool(v["short"])))
    rows = []
    for e in cfg:
        name = e["name"]
        vs = sorted(by.get(name, []))
        days_up = sorted({t.astimezone(KST).date() for t, _ in vs})
        gaps = [(b - a).days for a, b in zip(days_up, days_up[1:])][-10:]
        usual = round(statistics.median(gaps), 1) if len(gaps) >= 2 else None
        target = e.get("every_days") or usual
        last = vs[-1][0] if vs else None
        since = round((now - last).total_seconds() / 86400, 1) if last else None
        limit = round(target * 1.5 + 0.5, 1) if target else None
        nb = sorted(booked.get(name, []))
        late = bool(since is not None and limit and since > limit) and not nb
        count = {}
        for t, short in vs:
            d = t.astimezone(KST).strftime("%Y-%m-%d")
            if d >= dates[0]:
                count.setdefault(d, [0, 0])[0 if short else 1] += 1
        rows.append({"name": name, "n": len(vs), "usual": usual, "target": target, "set": bool(e.get("every_days")),
                     "last": last.astimezone(KST).strftime("%Y-%m-%d %H:%M") if last else None, "since": since, "limit": limit,
                     "late": late, "late_by": round(since - limit, 1) if late else 0,
                     "due": (last + timedelta(days=target)).astimezone(KST).strftime("%Y-%m-%d") if last and target else None,
                     "late_at": (last + timedelta(days=limit)).astimezone(KST).strftime("%Y-%m-%d %H:%M") if last and limit else None,
                     "n28": sum(sum(x) for x in count.values()), "cal": [count.get(d, [0, 0]) for d in dates],
                     "next": nb[0] if nb else None, "until": nb[-1] if nb else None, "booked": len(nb)})
    return {"dates": dates, "rows": rows}


def build(ctx):
    now, info, videos, vhist, hist = ctx["now"], ctx["info"], ctx["videos"], ctx["vhist"], ctx["hist"]
    early, money_hist, alerts, bench = ctx["early"], ctx["money_hist"], ctx["alerts"], ctx["bench"]
    days = sorted(hist["daily"])
    today = now.strftime("%Y-%m-%d") if now.strftime("%Y-%m-%d") in hist["daily"] else days[-1]
    prev_day = max([d for d in days if d < today], default=None)
    cur, prev = hist["daily"][today], (hist["daily"][prev_day] if prev_day else None)

    def delta(name, key):
        if not prev or name not in prev or name not in cur:
            return None
        return cur[name][key] - prev[name][key]

    chans = []
    for c in info:
        s = cur.get(c["name"])
        if not s:
            continue
        mine = [v for v in videos.values() if v["ch"] == c["name"]]
        chans.append({**c, **s, "url": f"https://www.youtube.com/channel/{c['id']}",
                      "d_subs": delta(c["name"], "subs"), "d_views": delta(c["name"], "views"),
                      "d_shorts": delta(c["name"], "shorts_views"), "d_long": delta(c["name"], "long_views"),
                      "likes": sum(v["likes"] for v in mine), "comments": sum(v["comments"] for v in mine),
                      "money": monetization(now, c["name"], s, mine, hist)})
    series_days = days[-61:]
    by_ch = {}
    for c in chans:
        rows = {"views": [], "shorts": [], "long": [], "subs": [], "subs_gain": []}
        for a, b in zip(series_days, series_days[1:]):
            A, B = hist["daily"][a].get(c["name"]), hist["daily"][b].get(c["name"])
            ok = A is not None and B is not None
            rows["views"].append(B["views"] - A["views"] if ok else None)
            rows["shorts"].append(B["shorts_views"] - A["shorts_views"] if ok else None)
            rows["long"].append(B["long_views"] - A["long_views"] if ok else None)
            rows["subs"].append(B["subs"] if B else None)
            # 날짜별 구독자 증가(2026-10-05 사용자 요청) — 그날 마지막 수집값 − 전날 마지막 수집값. 숨긴 채널은 0으로 와서 비운다
            rows["subs_gain"].append(B["subs"] - A["subs"] if ok and not (A.get("hidden") or B.get("hidden")) else None)
        by_ch[c["name"]] = rows

    week_start = max([d for d in days if d <= (datetime.fromisoformat(today) - timedelta(days=7)).strftime("%Y-%m-%d")], default=days[0])
    engaged = load("engaged.json", {})
    ev = engaged.get("videos") or {}
    vids = []
    for vid, v in videos.items():
        h = vhist.get(vid, {})
        before = max([d for d in h if d < today], default=None)
        week = [d for d in h if week_start <= d < today]
        age = max(0.0, (now - parse_time(v["published"])).total_seconds() / 86400)
        e = early.get(vid, {})
        checks = {}
        for hour in EARLY_HOURS:
            if str(hour) in e:
                med = median_early(early, videos, v["ch"], v["short"], hour, vid)
                checks[str(hour)] = {"views": e[str(hour)][1], "ratio": round(e[str(hour)][1] / med, 2) if med else None, "median": med}
        pub_kst = parse_time(v["published"]).astimezone(KST)
        vids.append({"id": vid, "ch": v["ch"], "title": v["title"], "short": bool(v["short"]), "views": v["views"],
                     "gain": (v["views"] - h[before]) if before else None,
                     "gain7": (v["views"] - h[min(week)]) if week else None,
                     "per_day": round(v["views"] / max(1.0, age), 1), "age": round(age, 2),
                     "published": pub_kst.strftime("%Y-%m-%d"), "hm": pub_kst.strftime("%H:%M"), "pub_wd": pub_kst.weekday(), "pub_hour": pub_kst.hour,
                     "dur": v["dur"], "thumb": v["thumb"], "likes": v["likes"], "comments": v["comments"],
                     "like_rate": round(v["likes"] / v["views"] * 100, 2) if v["views"] else None,
                     "comment_rate": round(v["comments"] / v["views"] * 100, 2) if v["views"] else None,
                     "early": checks, "tracked": bool(e) or age <= 2, **({} if v.get("public", True) else {"public": False}),
                     # 유효 조회수(유튜브 분석): eng 유효 · eviews 분석 조회수(다시 보기 포함) · erate 유효 비율 · avp 평균 시청 비율 · esubs 구독 증가 · eng7 최근 7일 유효
                     **({"eng": ev[vid]["eng"], "eviews": ev[vid]["views"], "erate": round(ev[vid]["eng"] / ev[vid]["views"] * 100, 1) if ev[vid]["views"] else None,
                         "avp": ev[vid]["avp"], "esubs": ev[vid]["subs"], "eng7": ev[vid]["eng7"]} if vid in ev else {}),
                     "url": f"https://www.youtube.com/{'shorts/' if v['short'] else 'watch?v='}{vid}"})

    # 주간 리포트
    span = (datetime.fromisoformat(today) - datetime.fromisoformat(week_start)).days
    wchans = []
    for c in chans:
        A, B = hist["daily"][week_start].get(c["name"]), cur.get(c["name"])
        if not A or not B:
            continue
        mine = [x for x in vids if x["ch"] == c["name"] and x["gain7"]]
        best = max(mine, key=lambda x: x["gain7"], default=None)
        mh_before = money_hist.get(week_start, {}).get(c["name"], {})
        dv = B["views"] - A["views"]
        ds = B["subs"] - A["subs"]
        wchans.append({"name": c["name"], "thumb": c["thumb"], "d_views": dv, "d_subs": ds,
                       "d_shorts": B["shorts_views"] - A["shorts_views"], "d_long": B["long_views"] - A["long_views"],
                       "subs_per_1k": round(ds / dv * 1000, 1) if dv > 0 else None,
                       "uploads": sum(1 for x in vids if x["ch"] == c["name"] and x["published"] > week_start),
                       "best": {k: best[k] for k in ("title", "url", "thumb", "short")} | {"gain": best["gain7"]} if best else None,
                       "ads_now": next(t["overall"] for t in c["money"]["tiers"] if t["key"] == "ads"),
                       "ads_before": mh_before.get("ads")})
    weekly = {"days": span, "from": week_start, "to": today, "channels": wchans,
              "total": {k: sum(x[k] for x in wchans) for k in ("d_views", "d_subs", "d_shorts", "d_long")}}

    # 업로드 시간(요일·시간대별 평균 성적)
    def bucket_stats(key_fn, labels):
        out = []
        for i, lab in enumerate(labels):
            group = [x for x in vids if key_fn(x) == i and x["views"] > 0 and x["age"] >= 1]
            vals24 = [x["early"]["24"]["views"] for x in group if "24" in x["early"]]
            vals = vals24 if len(vals24) >= 3 else [x["per_day"] for x in group]
            out.append({"label": lab, "n": len(group), "avg": round(sum(vals) / len(vals), 1) if vals else None})
        return out
    slots = ["새벽 0~6시", "오전 6~12시", "오후 12~18시", "저녁 18~24시"]
    timing = {"weekday": bucket_stats(lambda x: x["pub_wd"], ["월", "화", "수", "목", "금", "토", "일"]),
              "slot": bucket_stats(lambda x: x["pub_hour"] // 6, slots), "n": sum(1 for x in vids if x["age"] >= 1)}

    # 벤치마크
    bvids = []
    for vid, v in (bench.get("videos") or {}).items():
        age = max(1 / 24, (now - parse_time(v["published"])).total_seconds() / 86400)
        if age > 14:
            continue
        bvids.append({"id": vid, "ch": v["ch"], "title": v["title"], "short": bool(v["short"]), "views": v["views"],
                      "per_day": round(v["views"] / max(1.0, age), 1), "age": round(age, 1), "thumb": v["thumb"],
                      "published": parse_time(v["published"]).astimezone(KST).strftime("%Y-%m-%d"),
                      "url": f"https://www.youtube.com/{'shorts/' if v['short'] else 'watch?v='}{vid}"})
    bvids.sort(key=lambda x: -x["per_day"])

    def total(key):
        vals = [c[key] for c in chans]
        return None if any(x is None for x in vals) else sum(vals)

    costs, topics = load_costs(chans), load_topics()
    med3 = median3(videos, vhist, now)
    sched = schedule(videos, now)
    data = {"updated": now.strftime("%Y-%m-%d %H:%M"), "prev_day": prev_day, "channels": chans,
            "totals": {k: total(k) for k in ("subs", "views", "shorts_views", "long_views", "d_subs", "d_views", "d_shorts", "d_long")},
            "series": {"dates": series_days[1:], "by_channel": by_ch,
                       # 기록이 빠진 날이 있으면 그 칸의 증가는 며칠치가 합쳐져 있다 → 화면에 'N일치'로 표시
                       "span": [(datetime.fromisoformat(b) - datetime.fromisoformat(a)).days for a, b in zip(series_days, series_days[1:])]},
            "videos": vids,
            "alerts": alerts["items"][:120], "weekly": weekly, "timing": timing,
            "bench": {"at": bench.get("at"), "channels": bench.get("channels", []), "videos": bvids[:40]},
            "costs": costs, "outliers": load_outliers(), "topics": topics,
            "pipeline": pipeline(videos, vhist, med3, topics, now), "efficiency": efficiency(chans, vids, hist, costs, weekly, now),
            "schedule": sched, "cadence": cadence(videos, now, sched),
            "engaged": {"at": engaged.get("at"), "err": engaged.get("err"), "channels": engaged.get("channels") or {}},
            "telegram": bool(env_value("TELEGRAM_BOT_TOKEN") and env_value("TELEGRAM_CHAT_ID")) or bool(os.environ.get("TELEGRAM_ON")),
            "settings": {"surge_min": SURGE_MIN_PER_HOUR, "surge_ratio": SURGE_RATIO, "retention": RETENTION}}
    # 10-22 개편: 누가 보는지(유튜브 분석) · 인스타. 회의실(직원 그림)은 화면에서 뺐다
    aud = load("audience.json", {})
    data["audience"] = {"at": aud.get("at"), "channels": aud.get("channels") or {}}
    data["insta"] = insta_view(load("insta.json", {}), now)
    return data


def insta_view(store, now):
    """화면용 인스타: 시간별 기록은 빼고, 게시물은 어제 대비 조회 증가만 붙인다"""
    today = now.strftime("%Y-%m-%d")
    out = []
    for user, a in (store.get("accounts") or {}).items():
        if not a.get("profile"):
            out.append({"user": user, "err": a.get("err") or "아직 수집 전"})
            continue
        media = []
        for m in a.get("media") or []:
            vh = m.get("vh") or {}
            before = max([d for d in vh if d < today], default=None)
            media.append({k: v for k, v in m.items() if k != "vh"} | {"gain": (m["views"] - vh[before]) if before and m.get("views") is not None else None})
        out.append({"user": user, "err": a.get("err"), "profile": a["profile"], "hist": a.get("hist") or {},
                    "daily": {d: {k: v for k, v in x.items() if k != "_at"} for d, x in (a.get("daily") or {}).items()},
                    "demo": a.get("demo") or {}, "media": media, "media_at": a.get("media_at")})
    return {"at": store.get("at"), "accounts": out}


def write_page(data):
    html = (ROOT / "template.html").read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(html, encoding="utf-8")


def rebuild():
    hist = load("history.json", None)
    if not hist:
        sys.exit("저장된 데이터가 없습니다. 먼저 collect.py를 실행하세요")
    ctx = dict(now=datetime.now(KST), info=load("channels_info.json", []), videos=load("videos.json", {}), vhist=load("video_views.json", {}),
               hist=hist, early=load("video_early.json", {}), money_hist=load("money_hist.json", {}),
               alerts=load("alerts.json", {"items": [], "seen": []}), bench=load("bench.json", {}))
    data = build(ctx)
    write_page(data)
    print(f"✔ {data['updated']} 대시보드 다시 만듦")


def check():
    for entry in json.loads((ROOT / "channels.json").read_text(encoding="utf-8")):
        for h in entry.get("handles", []):
            r = get("channels", part="snippet,statistics", forHandle=h)
            if r.get("items"):
                it = r["items"][0]
                print(f"{entry['name']:<6} {h:<14} → '{it['snippet']['title']}' 구독 {int(it['statistics'].get('subscriberCount', 0)):,}"
                      f" · 영상 {it['statistics'].get('videoCount')} · {it['snippet'].get('customUrl', '')}")
            else:
                print(f"{entry['name']:<6} {h:<14} → 없음")


if __name__ == "__main__":
    if "--build" in sys.argv:
        rebuild()
    else:
        KEY = env_value("YOUTUBE_API_KEY")
        if not KEY:
            sys.exit("YOUTUBE_API_KEY가 없습니다 (.env 또는 환경변수)")
        check() if "--check" in sys.argv else collect()
