#!/usr/bin/env python3
"""유튜브 채널 대시보드 수집기.

1시간마다 실행: 채널·영상 공개 통계를 받아 data/에 쌓고, docs/index.html(대시보드)을 새로 만든다.
  python3 collect.py            # 수집 + 알림 + 대시보드 생성
  python3 collect.py --check    # 채널 찾기만 확인(핸들 → 채널 이름·구독자)
  python3 collect.py --build    # 수집 없이 저장된 데이터로 대시보드만 다시 생성
키: 환경변수 YOUTUBE_API_KEY 또는 같은 폴더 .env (값은 절대 출력하지 않음)
    텔레그램 알림(선택): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

- 쇼츠 구분: 3분 이하 영상만 youtube.com/shorts/ID 주소가 열리는지로 판별(결과 캐시)
- 수익 창출 진행률: 공개 API로 알 수 없는 시청 시간은 '본편 조회수 × 영상 길이 × 평균 시청 비율'로 추정
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
RETENTION = 0.35              # 본편 평균 시청 비율 가정(시청 시간 추정용)
EARLY_HOURS = (6, 24, 48)     # 새 영상 성적 확인 시점
SURGE_MIN_PER_HOUR = 50       # 급등: 1시간 조회수 최소
SURGE_RATIO = 3               # 급등: 평소 시간당 조회수의 몇 배
BENCH_EVERY_HOURS = 6
SUBS_GOALS = (10, 50, 100, 300, 500, 1000, 5000, 10000, 50000, 100000)
VIDEO_GOALS = (1000, 10000, 100000, 1000000)
CHANNEL_GOALS = (10000, 100000, 1000000, 10000000)

# 유튜브 파트너 프로그램 기준(2026-09 기준 공개 안내)
TIERS = [
    {"key": "fan", "name": "1단계 · 팬 후원 기능", "desc": "멤버십·슈퍼 땡스 등(국가별 적용은 스튜디오에서 확인)",
     "subs": 500, "uploads90": 3, "watch": 3000, "shorts90": 3_000_000},
    {"key": "ads", "name": "2단계 · 광고 수익", "desc": "롱폼·쇼츠 광고 수익 공유",
     "subs": 1000, "uploads90": 0, "watch": 4000, "shorts90": 10_000_000},
]


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
    in_days = lambda v, n: parse_time(v["published"]) >= now - timedelta(days=n)
    public = [v for v in mine if v.get("public", True)]
    shorts90 = sum(v["views"] for v in public if v["short"] and in_days(v, 90))
    uploads90 = sum(1 for v in public if in_days(v, 90))
    longs = [v for v in public if not v["short"] and in_days(v, 365)]
    watch = sum(v["views"] * v["dur"] * RETENTION for v in longs) / 3600
    avg_long = (sum(v["dur"] for v in longs) / len(longs)) if longs else 0
    lr = rate(hist, name, "long_views")
    cur = {"subs": snap["subs"], "uploads90": uploads90, "watch": round(watch, 1), "shorts90": shorts90}
    speed = {"subs": rate(hist, name, "subs"), "shorts90": rate(hist, name, "shorts_views"),
             "watch": (lr * avg_long * RETENTION / 3600) if lr is not None else None, "uploads90": None}
    tiers = []
    for t in TIERS:
        items = []
        for key, label, unit in (("subs", "구독자", "명"), ("uploads90", "최근 90일 공개 업로드", "개"),
                                 ("watch", "최근 12개월 본편 시청 시간(추정)", "시간"), ("shorts90", "최근 90일 쇼츠 조회수", "회")):
            goal = t[key]
            if not goal:
                continue
            left = max(0, goal - cur[key])
            sp = speed[key]
            eta = None if left == 0 else (round(left / sp) if sp and sp > 0 else None)
            items.append({"key": key, "label": label, "unit": unit, "cur": cur[key], "goal": goal,
                          "pct": min(100.0, cur[key] / goal * 100), "left": left, "eta": eta, "speed": sp})
        by = {i["key"]: i for i in items}
        path = max(by["watch"]["pct"], by["shorts90"]["pct"])  # 시청 시간 또는 쇼츠 조회수 중 하나만 채우면 됨
        need = [by["subs"]["pct"], path] + ([by["uploads90"]["pct"]] if "uploads90" in by else [])
        tiers.append({"key": t["key"], "name": t["name"], "desc": t["desc"], "items": items,
                      "overall": min(need), "done": min(need) >= 100,
                      "best_path": "watch" if by["watch"]["pct"] >= by["shorts90"]["pct"] else "shorts90"})
    return {"tiers": tiers, "retention": RETENTION}


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
                prev = pts[-1] if pts else None
                pts.append([now.isoformat(timespec="minutes"), rec["views"]])
                if is_new and not first_run:
                    alert("upload", name, f"새 {kind}{'가' if kind == '쇼츠' else '이'} 올라왔어요", rec["title"], url)
                # 급등: 직전 기록 대비 시간당 조회수가 평소의 3배 이상
                if prev:
                    gap_h = (now - datetime.fromisoformat(prev[0])).total_seconds() / 3600
                    if 0.4 <= gap_h <= 3:
                        per_h = (rec["views"] - prev[1]) / gap_h
                        base = views_near(pts[:-1], now - timedelta(hours=25), timedelta(hours=3))
                        base_h = None
                        if base:
                            span = (datetime.fromisoformat(prev[0]) - base[0]).total_seconds() / 3600
                            base_h = (prev[1] - base[1]) / span if span > 1 else None
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

    hist["hourly"] = [h for h in hist["hourly"] if h["t"] >= (now - timedelta(days=14)).isoformat()] + [{"t": now.isoformat(), "ch": snap}]
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
                alert("money", c["name"], f"{t['name']} 조건 달성! 🎉", "YouTube 스튜디오 → 수익 창출에서 신청할 수 있어요",
                      DASHBOARD_URL + "#money/" + urllib.parse.quote(c["name"]), key=f"money:{c['name']}:{t['key']}:done")
    money_hist[today] = money_today

    # 정리: 오래된 기록 줄이기
    cutoff = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    for vid in list(vhist):
        vhist[vid] = {d: n for d, n in vhist[vid].items() if d >= cutoff}
        if vid not in videos:
            vhist.pop(vid)
    hour_cut = (now - timedelta(days=8)).isoformat()
    vhour = {vid: [p for p in pts if p[0] >= hour_cut] for vid, pts in vhour.items() if vid in videos}
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

    return {"updated": now.strftime("%Y-%m-%d %H:%M"), "prev_day": prev_day, "channels": chans,
            "totals": {k: total(k) for k in ("subs", "views", "shorts_views", "long_views", "d_subs", "d_views", "d_shorts", "d_long")},
            "series": {"dates": series_days[1:], "by_channel": by_ch}, "videos": vids,
            "alerts": alerts["items"][:120], "weekly": weekly, "timing": timing,
            "bench": {"at": bench.get("at"), "channels": bench.get("channels", []), "videos": bvids[:40]},
            "telegram": bool(env_value("TELEGRAM_BOT_TOKEN") and env_value("TELEGRAM_CHAT_ID")) or bool(os.environ.get("TELEGRAM_ON")),
            "settings": {"surge_min": SURGE_MIN_PER_HOUR, "surge_ratio": SURGE_RATIO, "retention": RETENTION}}


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
