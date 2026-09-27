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

    def alert(kind, ch, title, detail="", url="", key=None):
        if key:
            if key in seen:
                return
            seen.add(key)
            if first_run:  # 처음 실행 때는 이미 지난 목표로 알림을 쏟아내지 않음
                return
        item = {"t": now.isoformat(timespec="minutes"), "type": kind, "ch": ch, "title": title, "detail": detail, "url": url}
        alerts["items"].insert(0, item)
        new_alerts.append(item)

    snap, info = {}, []
    for entry in channels:
        ch = None
        for h in entry["handles"]:
            r = get("channels", part="snippet,statistics,contentDetails", forHandle=h)
            if r.get("items"):
                handle, ch = h, r["items"][0]
                break
        if not ch:
            print(f"! {entry['name']}: 채널을 찾지 못함 ({', '.join(entry['handles'])})")
            continue
        name, st = entry["name"], ch["statistics"]
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
            alert("cadence", r["name"], f"업로드가 늦어요: 마지막 업로드 {r['since']:.0f}일 전", f"평소 {r['target']:g}일마다 올렸어요 · 업로드 달력에서 확인",
                  DASHBOARD_URL + "#insight/cadence", key=f"late|{r['name']}|{r['last']}")

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
                {k: t.get(k) for k in ("소재", "제목", "총점", "최신") if t.get(k) is not None} for t in r.get("topics", [])]})
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


def cadence(videos, now):
    """업로드 주기: 채널마다 평소 간격(올린 날짜끼리 최근 10번 간격의 중앙값 — channels.json 의 every_days 가 있으면 그 값),
    마지막 업로드, 늦어짐(평소의 1.5배 + 반나절을 넘김), 최근 28일 달력(날마다 [쇼츠, 본편] 편수)."""
    cfg = [e for e in read_json(ROOT / "channels.json", []) if e.get("name")]
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
        late = bool(since is not None and limit and since > limit)
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
                     "n28": sum(sum(x) for x in count.values()), "cal": [count.get(d, [0, 0]) for d in dates]})
    return {"dates": dates, "rows": rows}


# ---------------------------------------------------------------- 마케팅팀 회의(2026-09-27 사용자: "대시보드를 마케팅 부서처럼 — 직원들이 나눠서 대화하며 좋았던 점·부족한 점")
# 직원 7명이 대시보드 숫자만 보고 말한다. AI 를 부르지 않는다(토큰 0) — 10분마다 새로 쓰이고 숫자가 틀릴 일이 없다.
# 말에는 **굵게** 표시만 쓴다(화면에서 굵은 글씨). tone: good(좋음) bad(아쉬움) idea(제안) info(보고).
STAFF = {   # 화면(template)도 이 명단을 그대로 쓴다
    "lead": {"name": "한결", "role": "마케팅 팀장", "emoji": "👔", "color": "#6c5ce7",
             "desc": "회의를 열고 닫아요. 이번 주 집중할 채널과 오늘 할 일을 정해요.", "tabs": [["회의실", "#summary"], ["팀 소개", "#team"]]},
    "analyst": {"name": "서윤", "role": "데이터 분석가", "emoji": "📊", "color": "#2b6de0",
                "desc": "조회수·구독자 흐름과 채널 효율을 봐요. 어디서 늘고 어디서 줄었는지 먼저 말해요.",
                "tabs": [["채널 효율", "#insight/efficiency"], ["주간 리포트", "#insight/weekly"], ["채널", "#channel"]]},
    "reviewer": {"name": "도현", "role": "성과 리뷰어", "emoji": "🎬", "color": "#e0392b",
                 "desc": "새 영상이 평소보다 잘 되는지, 어떤 제목 패턴이 먹히는지 봐요.",
                 "tabs": [["새 영상 성적", "#insight/early"], ["반응률", "#insight/engage"], ["영상", "#videos"]]},
    "trend": {"name": "하린", "role": "트렌드 리서처", "emoji": "🔥", "color": "#ff7a00",
              "desc": "지금 유튜브에서 평소보다 몇 배 빨리 크는 영상, 참고 채널, 검색 급상승을 찾아요.",
              "tabs": [["발굴", "#hunt"], ["벤치마크", "#insight/bench"]]},
    "planner": {"name": "지우", "role": "콘텐츠 기획자", "emoji": "🎯", "color": "#1f9d6b",
                "desc": "채널마다 소재 20개를 골라 두고, 만들기로 한 소재가 어디까지 왔는지 챙겨요.",
                "tabs": [["소재 추천", "#topics"], ["제작 현황", "#topics/제작"]]},
    "scheduler": {"name": "민재", "role": "편성 매니저", "emoji": "📅", "color": "#00a3a3",
                  "desc": "채널마다 올리는 간격을 지키는지, 늦어진 채널이 없는지 봐요.",
                  "tabs": [["업로드 달력", "#insight/cadence"], ["업로드 시간", "#insight/timing"]]},
    "money": {"name": "유나", "role": "수익·비용 담당", "emoji": "💰", "color": "#d4a106",
              "desc": "광고 수익 조건까지 얼마나 남았는지, 편당 제작비가 알맞은지 봐요.", "tabs": [["수익", "#money"], ["제작비", "#cost"]]},
}


def _batchim(w):
    w = re.sub(r"[\s)\]'\"’”.·*…]+$", "", str(w))
    if not w:
        return False
    c = w[-1]
    if "가" <= c <= "힣":
        return (ord(c) - 0xAC00) % 28 != 0
    if c.isdigit():
        return c in "0136789"          # 영·일·삼·육·칠·팔·구(구는 받침 없음 → 아래에서 뺌)
    return c.lower() in "lmn"         # 영어는 끝소리로 어림: …문(n)·…발(l)은 받침, Desk(데스크)처럼 k·t·p 로 끝나면 받침 없음


def jo(w, pair):
    """받침에 맞는 조사: jo('거대한비밀', '이/가') → '이'. '이에요/예요', '으로/로'(ㄹ 받침은 로)도."""
    a, b = pair.split("/")
    if pair == "으로/로":
        w2 = re.sub(r"[\s)\]'\"’”.·*…]+$", "", str(w))
        if w2 and "가" <= w2[-1] <= "힣" and (ord(w2[-1]) - 0xAC00) % 28 == 8:   # ㄹ 받침
            return b
    if str(w).rstrip()[-1:] == "9":
        return b
    return a if _batchim(w) else b


def bae(x):
    return f"{round(x)}배" if x >= 10 else (f"{x:.1f}".rstrip("0").rstrip(".") + "배")


def short(t, n=26):
    t = re.sub(r"\s+", " ", re.sub(r"\s*#\S+", "", str(t or ""))).strip()
    if len(t) <= n:
        return t
    cut = t[:n].rsplit(" ", 1)[0]
    return (cut if len(cut) >= n * 0.6 else t[:n]).rstrip(",·") + "…"


STAFF_ORDER = ("analyst", "reviewer", "trend", "planner", "scheduler", "money")
Q_TITLE = re.compile(r"(까|까요)\s*[?？]?(\s*#\S+)*\s*$|[?？](\s*#\S+)*\s*$")
N_TITLE = re.compile(r"\d")


def meeting(D, now):
    R = {k: [] for k in ("lead",) + STAFF_ORDER}
    todo = []
    q = urllib.parse.quote

    def say(who, text, tone="info", link=None, pri=5):
        R[who].append({"who": who, "text": text, "tone": tone, "link": link, "pri": pri})

    def do(who, text, link=None):
        if not any(t["text"] == text for t in todo):
            todo.append({"who": who, "text": text, "link": link})

    chans = D.get("channels") or []
    names = [c["name"] for c in chans]
    byc = (D.get("series") or {}).get("by_channel") or {}
    E, P, C = D.get("efficiency") or {}, D.get("pipeline") or {}, D.get("cadence") or {}
    T = (D.get("topics") or {}).get("channels") or {}
    vids = D.get("videos") or []
    focus = (E.get("focus") or {}).get("name")
    kind = "아침 회의" if 5 <= now.hour < 11 else ("오후 회의" if now.hour < 17 else "저녁 회의")

    def gain(n, k=-2, key="views"):
        arr = (byc.get(n) or {}).get(key) or []
        return arr[k] if len(arr) >= -k and arr[k] is not None else None

    def sect(fn):
        try:
            fn()
        except Exception as e:   # 한 사람 말이 막혀도 회의는 계속
            print(f"! 회의 준비 중 오류({fn.__name__}): {type(e).__name__} {e}")

    def opening():
        y = sum(g for g in (gain(n) for n in names) if g is not None)
        yy = sum(g for g in (gain(n, -3) for n in names) if g is not None)
        ys = 0
        for n in names:
            a = (byc.get(n) or {}).get("subs") or []
            if len(a) >= 3 and a[-2] is not None and a[-3] is not None:
                ys += a[-2] - a[-3]
        t = (D.get("totals") or {}).get("d_views")
        cmp_ = ""
        if yy > 0:
            cmp_ = f"(그제의 {bae(y / yy)})" if y / yy >= 3 else f"(그제보다 {round((y - yy) / yy * 100):+d}%)"
        txt = f"{kind} 시작할게요. 어제 하루 전체 조회 **+{fmt(y)}**{cmp_}, 구독 **{ys:+,}명**이었어요." + (f" 오늘은 {now.hour}시 기준 **+{fmt(t)}**까지 왔어요." if t is not None else "")
        say("lead", txt, "info", None, 0)

    def analyst():
        y = sum(g for g in (gain(n) for n in names) if g is not None)
        top = max(names, key=lambda n: gain(n) or -1) if names else None
        if top and (gain(top) or 0) > 0:
            share = round(gain(top) / y * 100) if y else 0
            say("analyst", f"어제 조회는 **{top}**{jo(top, '이/가')} +{fmt(gain(top))}{jo(fmt(gain(top)), '으로/로')} 전체의 {share}%였어요.", "good", "#channel/" + q(top), 1)
        live = {v["ch"] for v in vids}   # 공개 영상이 없는 채널(이름을 바꾸며 옛 영상을 내린 채널 등)은 비교하지 않는다
        for n in names:
            # 평소 = 최근 7일 하루 증가의 중앙값(하루 튄 날 하나에 끌려가지 않게, 유튜브 보정으로 생긴 마이너스는 0)
            arr = [max(x, 0) for x in ((byc.get(n) or {}).get("views") or [])[-9:-2] if x is not None]
            yv = gain(n)
            yv = max(yv, 0) if yv is not None else None
            if n in live and len(arr) >= 5 and yv is not None:
                avg = statistics.median(arr)
                if avg >= 200 and yv < avg * 0.5:
                    how = "거의 안 늘었어요" if yv < avg * 0.05 else f"평소의 {round(yv / avg * 100)}%로 줄었어요"
                    say("analyst", f"**{n}**{jo(n, '은/는')} 어제 조회가 {how}(보통 하루 {fmt(avg)}회, 어제 +{fmt(yv)}).", "bad", "#channel/" + q(n), 2)
                elif avg >= 100 and yv > avg * 2:
                    say("analyst", f"**{n}**{jo(n, '은/는')} 어제 조회가 평소의 {bae(yv / avg)}로 튀었어요(보통 하루 {fmt(avg)}회, 어제 +{fmt(yv)}).", "good", "#channel/" + q(n), 2)
        rows = sorted([r for r in (E.get("rows") or []) if r.get("w7")], key=lambda r: -r["w7"])[:3]
        if rows:
            say("analyst", "최근 7일은 " + " · ".join(f"{r['name']} +{fmt(r['w7'])}" + (f"({r['growth']:+d}%)" if r.get("growth") is not None else "")
                                                 for r in rows) + " 순이에요.", "info", "#insight/efficiency", 3)
        W = D.get("weekly") or {}
        wk = sorted(W.get("channels") or [], key=lambda c: -(c.get("d_subs") or 0))
        if wk and (wk[0].get("d_subs") or 0) > 0:
            c = wk[0]
            say("analyst", f"구독은 **{c['name']}**{jo(c['name'], '이/가')} {W.get('days')}일 동안 +{fmt(c['d_subs'])}명으로 가장 많이 늘었어요"
                + (f"(조회 1천 회당 {c['subs_per_1k']}명)" if c.get("subs_per_1k") is not None else "") + ".", "good", "#insight/weekly", 4)
        if focus:
            say("analyst", f"효율로 보면 이번 주 집중할 채널은 **{focus}**{jo(focus, '이에요/예요')}. {E['focus']['why'][0]}예요.", "idea", "#insight/efficiency", 1.5)

    def reviewer():
        likes = {c["name"]: c["likes"] / (c["shorts_views"] + c["long_views"]) * 100 for c in chans if (c["shorts_views"] + c["long_views"]) > 0}

        def er(v):
            for h in ("24", "6", "48"):
                e = (v.get("early") or {}).get(h)
                if e and e.get("ratio") is not None:
                    return h, e["ratio"], e["views"]
            return None
        fresh = [(v, er(v)) for v in vids if v["age"] <= 3]
        rated = [(v, r) for v, r in fresh if r]
        if rated:
            bv, (h, ratio, views) = max(rated, key=lambda x: x[1][1])
            if ratio >= 1.3:
                ti = short(bv["title"])
                txt = f"{bv['ch']}의 새 {'쇼츠' if bv['short'] else '본편'} **'{ti}'**{jo(ti, '이/가')} {h}시간에 {fmt(views)}회로 평소의 **{bae(ratio)}**예요."
                lr, avg = bv.get("like_rate"), likes.get(bv["ch"])
                if lr and avg and lr >= avg * 1.5 and bv["views"] >= 100:
                    txt += f" 좋아요율도 {lr:.1f}%로 채널 평균 {avg:.1f}%보다 높아서, 비슷한 소재를 더 만들 만해요."
                say("reviewer", txt, "good", bv["url"], 1)
            wv, (h2, r2, v2) = min(rated, key=lambda x: x[1][1])
            if r2 <= 0.6 and wv is not bv:
                ti = short(wv["title"])
                say("reviewer", f"반대로 {wv['ch']}의 **'{ti}'**{jo(ti, '은/는')} {h2}시간 성적이 평소의 {bae(r2)}라 아쉬워요. 제목 앞 두세 단어와 첫 장면을 다시 볼 만해요.", "bad", wv["url"], 2)
                do("reviewer", f"'{short(wv['title'], 22)}' 제목·첫 장면 점검 (24시간 평소의 {bae(r2)})", wv["url"])
        elif fresh:
            say("reviewer", f"최근 3일 새 영상 {len(fresh)}편은 아직 비교 기록(6시간)이 쌓이는 중이에요.", "info", "#insight/early", 4)
        cut = (now - timedelta(hours=24)).isoformat()
        surges = [a for a in (D.get("alerts") or []) if a.get("type") == "surge" and a.get("t", "") >= cut]
        if surges:
            say("reviewer", f"지난 24시간 급등 알림이 {len(surges)}번 있었어요 — 가장 최근은 {surges[0]['ch']}의 '{short(surges[0].get('detail'))}'.", "good", "#insight/alerts", 3)
        best = None   # 제목 패턴: 같은 채널·같은 종류 안에서 24시간 조회 중앙값 비교(각 3편 이상)
        for rx, label in ((Q_TITLE, "질문으로 끝나는(…을까)"), (N_TITLE, "숫자가 들어간")):
            for n in names:
                for is_s in (True, False):
                    vs = [v for v in vids if v["ch"] == n and v["short"] == is_s and "24" in (v.get("early") or {})]
                    a = [v["early"]["24"]["views"] for v in vs if rx.search(v["title"])]
                    b = [v["early"]["24"]["views"] for v in vs if not rx.search(v["title"])]
                    if len(a) >= 3 and len(b) >= 3:
                        ma, mb = statistics.median(a), statistics.median(b)
                        if ma > 0 and mb > 0 and max(ma, mb) >= 300:
                            k = max(ma / mb, mb / ma)
                            if k >= 1.5 and (best is None or k > best[0]):
                                best = (k, n, is_s, label, ma, mb, len(a), len(b))
        if best:
            k, n, is_s, label, ma, mb, na, nb = best
            better = ma > mb
            say("reviewer", f"패턴 하나 찾았어요: **{n}** {'쇼츠는' if is_s else '본편은'} {label} 제목의 24시간 조회 중앙값이 {fmt(ma)}로, "
                f"아닌 제목({fmt(mb)})보다 **{k:.1f}배 {'높아요' if better else '낮아요'}** ({na}편 대 {nb}편).", "idea", "#videos", 2.5)

    def trend():
        O = D.get("outliers") or {}
        byurl = {r.get("url"): r for r in (O.get("shorts") or []) + (O.get("long") or []) if r.get("url")}
        for ch, cv in T.items():   # 추천이 실제 근거로 쓴 '지금 크는 영상'만 말한다(흔한 낱말로 엮으면 엉뚱한 영상이 나와서)
            ev = [(byurl[e["url"]], i, t) for i, t in enumerate(cv.get("topics") or [], 1) for e in (t.get("근거") or []) if e.get("url") in byurl]
            if ev:
                r, i, t = max(ev, key=lambda x: x[0].get("mult") or 0)
                ti = short(r.get("title"))
                say("trend", f"**{ch}** 추천 {i}위 '{short(t.get('소재'), 24)}'의 근거 영상 **'{ti}'**{jo(ti, '이/가')} 지금 평소의 **{bae(r.get('mult') or 0)}**로 "
                    f"크고 있어요(구독 {fmt(r.get('subs') or 0)} 채널). 이 소재는 지금이 타이밍이에요.", "idea", r.get("url"), 1)
            g = (cv.get("genre_hot") or [None])[0]
            if g and (g.get("평소대비") or 0) >= 2:
                ti = short(g.get("제목"))
                say("trend", f"**{ch}**{jo(ch, '과/와')} 같은 장르에선 {g.get('채널')}의 **'{ti}'**{jo(ti, '이/가')} 평소의 {bae(g['평소대비'])}로 크고 있어요.", "idea", g.get("url"), 1.2)
        tr = (D.get("topics") or {}).get("trends") or []
        if tr:
            say("trend", "지금 검색 급상승: " + " · ".join(f"{t.get('검색어')}({t.get('검색량')})" for t in tr[:5]) + ". 채널 공식에 맞는 말만 추천에 넣었어요.", "info", "#topics", 2)
        B = D.get("bench") or {}
        bfor = {c.get("name"): c.get("for") for c in (B.get("channels") or [])}
        bv = next((v for v in (B.get("videos") or []) if bfor.get(v.get("ch")) in names), None)   # 지금 있는 채널의 참고 채널만(옛 이유상자 참고 채널은 뺀다)
        if bv:
            ti = short(bv["title"])
            say("trend", f"**{bfor[bv['ch']]}** 참고 채널 중엔 **{bv['ch']}**의 '{ti}'{jo(ti, '이/가')} 하루 {fmt(bv['per_day'])}회로 가장 빨라요.", "info", bv.get("url"), 3)

    def planner():
        items = P.get("items") or []
        taken = {(x.get("ch"), x.get("소재")) for x in items}   # 이미 만들기로 한 소재는 다시 권하지 않는다
        free = lambda n: [(i, t) for i, t in enumerate(T[n].get("topics") or [], 1) if (n, t.get("소재")) not in taken]
        fch = focus if focus in T else (max(T, key=lambda n: ((free(n) or [(0, {})])[0][1].get("총점") or 0)) if T else None)
        if fch and free(fch):
            i, t0 = free(fch)[0]
            lead_in = f"서윤 님 말대로 이번 주 **{fch}**에 힘을 싣는다면, " if fch == focus else f"추천 점수로는 **{fch}**{jo(fch, '이/가')} 가장 높아요. "
            say("planner", lead_in + f"{'아직 안 고른 것 중 ' if i > 1 else ''}추천 {i}위 **'{t0.get('소재')}'**({t0.get('총점')}점"
                + (f", 📰 {str(t0['최신'])[5:].replace('-', '/')} 기사 근거" if t0.get("최신") else "") + ")부터 가면 좋겠어요.", "idea", "#topics/" + q(fch), 1)
        picked = sorted([x for x in items if x["status"] == "picked"], key=lambda x: x.get("picked_at") or "")
        making = [x for x in items if x["status"] == "making"]
        up = [x for x in items if x["status"] == "upload"]
        if items:
            txt = f"만들기로 한 소재는 {len(items)}개예요 — 제작 중 {len(making)} · 대기 {len(picked)} · 업로드 {len(up)}."
            for x in up[:1]:
                v = x.get("video") or {}
                if v.get("v3") is not None:
                    txt += f" {x['id']} '{short(x['소재'], 18)}'는 3일 조회 {fmt(v['v3'])}" + (f"(평소의 **{bae(v['ratio'])}**)" if v.get("ratio") else "") + "."
            say("planner", txt, "info", "#topics/제작", 2)
            for x in picked[:2]:
                try:
                    wait = (now - datetime.fromisoformat(str(x["picked_at"]).replace(" ", "T")).replace(tzinfo=KST)).days
                except Exception:
                    wait = 0
                do("planner", f"{x['id']} [{x['ch']}] '{short(x['소재'], 22)}' 제작 시작" + (f" (고른 지 {wait}일)" if wait >= 1 else ""), "#topics/제작")
        elif fch and T[fch].get("topics"):
            t0 = T[fch]["topics"][0]
            say("planner", "아직 만들기로 한 소재가 없어요. 번호를 말씀해 주시면(예: '" + f"{fch} 1위 만들어 줘') 제작 현황에 올릴게요.", "info", "#topics/제작", 3)
            do("planner", f"{fch} 추천 1위 '{short(t0.get('소재'), 22)}' 검토 — 만들려면 '{fch} 1위 만들어 줘'", "#topics/" + q(fch))
        if P.get("hit_n"):
            say("planner", f"지금까지 추천과 비슷한 영상 {P['hit_n']}편이 올라갔어요" + (f" — 3일 조회가 평소의 **{bae(P['hit_ratio'])}**예요." if P.get("hit_ratio") else ". 3일이 지나면 추천이 맞았는지 숫자가 나와요."),
                "good" if (P.get("hit_ratio") or 0) >= 1 else "info", "#topics/제작", 3)
        tot = sum(len(c.get("topics") or []) for c in T.values())
        fr = sum(c.get("fresh_n") or 0 for c in T.values())
        if tot:
            say("planner", f"지금 추천은 {len(T)}개 채널 {tot}개, 그중 {fr}개가 최근 2주 기사·검색어에 근거해요.", "info", "#topics", 4)

    def scheduler():
        rows = C.get("rows") or []
        late = sorted([r for r in rows if r["late"]], key=lambda r: r["late_by"])
        now_late = [r for r in late if r["late_by"] <= 7]
        resting = [r for r in late if r["late_by"] > 7]
        for r in now_late[:3]:
            say("scheduler", f"**{r['name']}**{jo(r['name'], '은/는')} 평소 {r['target']:g}일마다 올렸는데 마지막 업로드가 **{r['since']:.0f}일 전**이에요.", "bad", "#insight/cadence", 1)
            do("scheduler", f"{r['name']} 새 영상 올리기 (평소 {r['target']:g}일 간격, {r['since']:.0f}일째)", "#insight/cadence")
        if resting:
            names_ = "·".join(f"{r['name']}({r['since']:.0f}일째)" for r in resting)
            say("scheduler", f"{names_}{jo(resting[-1]['name'], '은/는')} 한동안 쉬는 중이에요. 일부러 멈춘 게 아니면 다시 시작할 때예요.",
                "info", "#insight/cadence", 2.5)
        ok = [r["name"] for r in rows if r["n"] >= 3 and not r["late"] and r["target"] and r["target"] <= 1.5]
        if ok:
            say("scheduler", f"{'·'.join(ok)}{jo(ok[-1], '은/는')} 매일 꾸준히 올라가고 있어요.", "good", "#insight/cadence", 3)
        soon = [r for r in rows if not r["late"] and r["n"] >= 3 and r["target"] and r["target"] >= 2 and r["due"]]
        today = now.astimezone(KST).strftime("%Y-%m-%d")

        def when(s):   # '2026-09-28 12:15' → '내일 12시'
            t = datetime.strptime(s, "%Y-%m-%d %H:%M")
            d = (t.date() - now.astimezone(KST).date()).days
            return ("오늘" if d == 0 else "내일" if d == 1 else f"{t:%m/%d}") + f" {t.hour}시"
        for r in soon[:2]:
            d, n = r["due"][5:].replace("-", "/"), r["name"]
            by = f" **{when(r['late_at'])}** 전에 올리면 '늦음'으로 넘어가지 않아요." if r.get("late_at") else ""
            if r["due"] <= today:
                say("scheduler", f"**{n}**{jo(n, '은/는')} " + (f"다음 편 차례({d})가 지났어요." if r["due"] < today else "오늘이 다음 편 차례예요.")
                    + f" 평소 {r['target']:g}일 간격이라{by or ' 오늘 올리면 좋아요.'}", "idea", "#insight/cadence", 2.8)
                if r.get("late_at"):
                    do("scheduler", f"{n} 다음 편 올리기 ({when(r['late_at'])} 전, 평소 {r['target']:g}일 간격)", "#insight/cadence")
            else:
                say("scheduler", f"{n} 다음 편 차례는 {d}쯤이에요(평소 {r['target']:g}일 간격).", "info", "#insight/cadence", 3.5)
        notyet = [r["name"] for r in rows if r["n"] == 0]
        if notyet:
            say("scheduler", f"{'·'.join(notyet)}{jo(notyet[-1], '은/는')} 공개된 영상 기록이 아직 없어요.", "info", "#insight/cadence", 4)

    def money():
        best = None
        for c in chans:
            ads = next((t for t in ((c.get("money") or {}).get("tiers") or []) if t["key"] == "ads"), None)
            if ads and (best is None or ads["overall"] > best[1]["overall"]):
                best = (c, ads)
        if best and best[1]["overall"] > 0:
            c, ads = best
            pc = f"{int(ads['overall'] * 10) / 10:g}%"   # 화면(수익·채널 효율 탭)과 같은 자리수: 소수 첫째 자리 버림
            blk = next((i for i in ads["items"] if i["key"] == ads.get("block")), None)
            txt = f"광고 수익 조건은 **{c['name']}**{jo(c['name'], '이/가')} {pc}로 가장 가까워요."
            if blk and blk.get("left"):
                txt += f" 막힌 건 {blk['label'].split(' · ')[0]} — {fmt(blk['left'])}{blk['unit']} 남았어요" + (f"(지금 속도면 약 {blk['eta']}일)" if blk.get("eta") else "") + "."
            say("money", txt, "info", "#money/" + q(c["name"]), 1)
            if ads["overall"] >= 75 and blk and blk.get("left"):
                do("money", f"{c['name']} 수익 조건 {pc} — {blk['label'].split(' · ')[0]} {fmt(blk['left'])}{blk['unit']} 남음", "#money/" + q(c["name"]))
        rows = [r for r in (((D.get("costs") or {}).get("채널")) or []) if r.get("천회당krw") and (r.get("조회수") or 0) >= 1000]
        if len(rows) >= 2:
            lo, hi = min(rows, key=lambda r: r["천회당krw"]), max(rows, key=lambda r: r["천회당krw"])
            say("money", f"조회 1천 회당 제작비는 **{lo['name']}** {lo['천회당krw']:,}원으로 가장 싸고, {hi['name']}{jo(hi['name'], '은/는')} {hi['천회당krw']:,}원이에요.",
                "bad" if hi["천회당krw"] > lo["천회당krw"] * 10 else "info", "#cost", 2)
        tc = D.get("costs") or {}
        if tc.get("합계krw"):
            say("money", f"지금까지 제작비는 {tc.get('편수')}편에 {tc['합계krw']:,}원이에요.", "info", "#cost", 3)

    for fn in (opening, analyst, reviewer, trend, planner, scheduler, money):
        sect(fn)
    for who in R:
        R[who].sort(key=lambda x: x["pri"])
    lines = list(R["lead"])
    for who in STAFF_ORDER:
        lines += R[who][:2]
    close = "정리할게요. " + (f"이번 주 집중은 **{focus}**{jo(focus, '이에요/예요')}. " if focus else "")
    close += f"오늘 할 일 {min(len(todo), 6)}가지를 아래에 적어 뒀어요 — 끝나면 체크해 주세요." if todo else "오늘은 급한 일 없이 추천 소재를 골라 보면 돼요."
    lines.append({"who": "lead", "text": close, "tone": "idea", "link": None, "pri": 9})
    strip = lambda xs: [{k: v for k, v in x.items() if k != "pri"} for x in xs]
    return {"at": now.strftime("%Y-%m-%d %H:%M"), "kind": kind, "focus": E.get("focus"), "staff": STAFF, "lines": strip(lines), "todo": todo[:6],
            "reports": {k: strip(v) for k, v in R.items()},
            "mood": {k: {"good": sum(1 for x in v if x["tone"] == "good"), "bad": sum(1 for x in v if x["tone"] == "bad")} for k, v in R.items()}}



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
        rows = {"views": [], "shorts": [], "long": [], "subs": []}
        for a, b in zip(series_days, series_days[1:]):
            A, B = hist["daily"][a].get(c["name"]), hist["daily"][b].get(c["name"])
            ok = A is not None and B is not None
            rows["views"].append(B["views"] - A["views"] if ok else None)
            rows["shorts"].append(B["shorts_views"] - A["shorts_views"] if ok else None)
            rows["long"].append(B["long_views"] - A["long_views"] if ok else None)
            rows["subs"].append(B["subs"] if B else None)
        by_ch[c["name"]] = rows

    week_start = max([d for d in days if d <= (datetime.fromisoformat(today) - timedelta(days=7)).strftime("%Y-%m-%d")], default=days[0])
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
                     "published": pub_kst.strftime("%Y-%m-%d"), "pub_wd": pub_kst.weekday(), "pub_hour": pub_kst.hour,
                     "dur": v["dur"], "thumb": v["thumb"], "likes": v["likes"], "comments": v["comments"],
                     "like_rate": round(v["likes"] / v["views"] * 100, 2) if v["views"] else None,
                     "comment_rate": round(v["comments"] / v["views"] * 100, 2) if v["views"] else None,
                     "early": checks, "tracked": bool(e) or age <= 2,
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
    data = {"updated": now.strftime("%Y-%m-%d %H:%M"), "prev_day": prev_day, "channels": chans,
            "totals": {k: total(k) for k in ("subs", "views", "shorts_views", "long_views", "d_subs", "d_views", "d_shorts", "d_long")},
            "series": {"dates": series_days[1:], "by_channel": by_ch}, "videos": vids,
            "alerts": alerts["items"][:120], "weekly": weekly, "timing": timing,
            "bench": {"at": bench.get("at"), "channels": bench.get("channels", []), "videos": bvids[:40]},
            "costs": costs, "outliers": load_outliers(), "topics": topics,
            "pipeline": pipeline(videos, vhist, med3, topics, now), "efficiency": efficiency(chans, vids, hist, costs, weekly, now),
            "cadence": cadence(videos, now),
            "telegram": bool(env_value("TELEGRAM_BOT_TOKEN") and env_value("TELEGRAM_CHAT_ID")) or bool(os.environ.get("TELEGRAM_ON")),
            "settings": {"surge_min": SURGE_MIN_PER_HOUR, "surge_ratio": SURGE_RATIO, "retention": RETENTION}}
    try:
        data["meeting"] = meeting(data, now)
    except Exception as e:   # 회의가 막혀도 대시보드는 그대로 만든다
        print(f"! 회의 만들기 실패: {type(e).__name__} {e}")
        data["meeting"] = None
    return data


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
        for h in entry["handles"]:
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
