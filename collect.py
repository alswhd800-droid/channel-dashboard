#!/usr/bin/env python3
"""유튜브 채널 대시보드 수집기.

1시간마다 실행: 채널·영상 공개 통계를 받아 data/에 쌓고, docs/index.html(대시보드)을 새로 만든다.
  python3 collect.py            # 수집 + 대시보드 생성
  python3 collect.py --check    # 채널 찾기만 확인(핸들 → 채널 이름·구독자)
  python3 collect.py --build    # 수집 없이 저장된 데이터로 대시보드만 다시 생성
키: 환경변수 YOUTUBE_API_KEY 또는 같은 폴더 .env (값은 절대 출력하지 않음)
쇼츠 구분: 3분 이하 영상만 youtube.com/shorts/ID 주소가 열리는지로 판별(결과 캐시).
수익 창출 진행률: 공개 API로 알 수 없는 시청 시간은 '본편 조회수 × 영상 길이 × 평균 시청 비율'로 추정한다.
"""
import json
import os
import re
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
RETENTION = 0.35  # 본편 평균 시청 비율 가정(시청 시간 추정용)

# 유튜브 파트너 프로그램 기준(2026-09 기준 공개 안내)
TIERS = [
    {"key": "fan", "name": "1단계 · 팬 후원 기능", "desc": "멤버십·슈퍼 땡스 등(국가별 적용은 스튜디오에서 확인)",
     "subs": 500, "uploads90": 3, "watch": 3000, "shorts90": 3_000_000},
    {"key": "ads", "name": "2단계 · 광고 수익", "desc": "롱폼·쇼츠 광고 수익 공유",
     "subs": 1000, "uploads90": 0, "watch": 4000, "shorts90": 10_000_000},
]


def load_key():
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("YOUTUBE_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("YOUTUBE_API_KEY가 없습니다 (.env 또는 환경변수)")
    return key


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


def load(name, default):
    p = DATA / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(name, obj):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def find_channel(entry):
    for h in entry["handles"]:
        r = get("channels", part="snippet,statistics,contentDetails", forHandle=h)
        if r.get("items"):
            return h, r["items"][0]
    return None, None


def collect():
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    channels = json.loads((ROOT / "channels.json").read_text(encoding="utf-8"))
    videos = load("videos.json", {})            # 영상 id → 최신 정보(+쇼츠 여부 캐시)
    vhist = load("video_views.json", {})         # 영상 id → {날짜: 조회수}
    hist = load("history.json", {"hourly": [], "daily": {}})
    snap, info = {}, []
    for entry in channels:
        handle, ch = find_channel(entry)
        if not ch:
            print(f"! {entry['name']}: 채널을 찾지 못함 ({', '.join(entry['handles'])})")
            continue
        st = ch["statistics"]
        uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
        ids, token = [], None
        while True:
            params = {"part": "contentDetails", "playlistId": uploads, "maxResults": 50}
            if token:
                params["pageToken"] = token
            try:
                r = get("playlistItems", **params)
            except SystemExit as e:
                if "playlistNotFound" in str(e):  # 영상이 하나도 없는 채널
                    break
                raise
            ids += [it["contentDetails"]["videoId"] for it in r.get("items", [])]
            token = r.get("nextPageToken")
            if not token:
                break
        idset = set(ids)
        for k in range(0, len(ids), 50):
            r = get("videos", part="snippet,contentDetails,statistics,status", id=",".join(ids[k:k + 50]))
            for v in r.get("items", []):
                old = videos.get(v["id"], {})
                dur = seconds(v["contentDetails"].get("duration"))
                short = old.get("short")
                if short is None:
                    short = is_short(v["id"]) if dur <= 180 else False
                    if short is None:
                        short = None if dur > 60 else True  # 확인 실패: 다음 실행 때 다시 확인
                thumbs = v["snippet"].get("thumbnails", {})
                videos[v["id"]] = {
                    "ch": entry["name"], "title": v["snippet"]["title"], "published": v["snippet"]["publishedAt"],
                    "dur": dur, "short": short, "views": int(v["statistics"].get("viewCount", 0)),
                    "likes": int(v["statistics"].get("likeCount", 0)), "comments": int(v["statistics"].get("commentCount", 0)),
                    "public": v.get("status", {}).get("privacyStatus", "public") == "public",
                    "thumb": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", ""),
                }
                vhist.setdefault(v["id"], {})[today] = videos[v["id"]]["views"]
        for vid in [vid for vid, v in videos.items() if v["ch"] == entry["name"] and vid not in idset]:
            videos.pop(vid)  # 채널에서 지워진 영상
        mine = [v for vid, v in videos.items() if v["ch"] == entry["name"]]
        snap[entry["name"]] = {
            "subs": int(st.get("subscriberCount", 0)), "hidden": bool(st.get("hiddenSubscriberCount")),
            "views": int(st.get("viewCount", 0)), "videos": int(st.get("videoCount", 0)),
            "shorts_views": sum(v["views"] for v in mine if v["short"]), "long_views": sum(v["views"] for v in mine if not v["short"]),
            "shorts_count": sum(1 for v in mine if v["short"]), "long_count": sum(1 for v in mine if not v["short"]),
        }
        info.append({"name": entry["name"], "handle": handle, "id": ch["id"], "title": ch["snippet"]["title"],
                     "thumb": ch["snippet"]["thumbnails"].get("default", {}).get("url", "")})
    if not snap:
        sys.exit("수집된 채널이 없습니다")
    hist["hourly"] = [h for h in hist["hourly"] if h["t"] >= (now - timedelta(days=14)).isoformat()] + [{"t": now.isoformat(), "ch": snap}]
    hist["daily"][today] = snap
    cutoff = (now - timedelta(days=40)).strftime("%Y-%m-%d")
    for vid in list(vhist):
        vhist[vid] = {d: n for d, n in vhist[vid].items() if d >= cutoff}
        if vid not in videos:
            vhist.pop(vid)
    save("videos.json", videos)
    save("video_views.json", vhist)
    save("history.json", hist)
    save("channels_info.json", info)
    build(now, info, videos, vhist, hist)


def rate(hist, name, key, days=7):
    """최근 며칠 하루 평균 증가량(기록이 2일 이상 있을 때)"""
    ds = [d for d in sorted(hist["daily"]) if name in hist["daily"][d]][-(days + 1):]
    if len(ds) < 2:
        return None
    first, last = hist["daily"][ds[0]][name][key], hist["daily"][ds[-1]][name][key]
    span = (datetime.fromisoformat(ds[-1]) - datetime.fromisoformat(ds[0])).days or 1
    return (last - first) / span


def monetization(now, name, snap, mine, hist):
    pub = lambda v: datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
    in_days = lambda v, n: pub(v) >= now - timedelta(days=n)
    public = [v for v in mine if v.get("public", True)]
    shorts90 = sum(v["views"] for v in public if v["short"] and in_days(v, 90))  # 90일 안에 올린 쇼츠의 조회수(채널이 새로워 거의 같음)
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


def build(now, info, videos, vhist, hist):
    today = now.strftime("%Y-%m-%d")
    days = sorted(hist["daily"])
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
    vids = []
    for vid, v in videos.items():
        h = vhist.get(vid, {})
        before = max([d for d in h if d < today], default=None)
        week = [d for d in h if (now - timedelta(days=7)).strftime("%Y-%m-%d") <= d < today]
        age = max(1.0, (now - datetime.fromisoformat(v["published"].replace("Z", "+00:00"))).total_seconds() / 86400)
        vids.append({"id": vid, "ch": v["ch"], "title": v["title"], "short": bool(v["short"]), "views": v["views"],
                     "gain": (v["views"] - h[before]) if before else None,
                     "gain7": (v["views"] - h[min(week)]) if week else None,     # 최근 7일(기록이 쌓인 만큼) 증가량
                     "per_day": round(v["views"] / age, 1), "age": round(age, 1),  # 올린 뒤 하루 평균 조회수(기록 없을 때 급등 판단용)
                     "published": v["published"][:10],
                     "dur": v["dur"], "thumb": v["thumb"], "likes": v["likes"], "comments": v["comments"],
                     "url": f"https://www.youtube.com/{'shorts/' if v['short'] else 'watch?v='}{vid}"})

    def total(key):
        vals = [c[key] for c in chans]
        return None if any(x is None for x in vals) else sum(vals)

    data = {"updated": now.strftime("%Y-%m-%d %H:%M"), "prev_day": prev_day, "channels": chans,
            "totals": {k: total(k) for k in ("subs", "views", "shorts_views", "long_views", "d_subs", "d_views", "d_shorts", "d_long")},
            "series": {"dates": series_days[1:], "by_channel": by_ch}, "videos": vids}
    html = (ROOT / "template.html").read_text(encoding="utf-8")
    html = html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    DOCS.mkdir(exist_ok=True)
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    print(f"✔ {data['updated']} 수집 완료: " + ", ".join(f"{c['name']} 구독 {c['subs']:,} · 조회 {c['views']:,}" for c in chans))


def rebuild():
    info, videos, vhist, hist = load("channels_info.json", []), load("videos.json", {}), load("video_views.json", {}), load("history.json", None)
    if not hist:
        sys.exit("저장된 데이터가 없습니다. 먼저 collect.py를 실행하세요")
    last = max(hist["daily"])
    build(datetime.now(KST).replace(year=int(last[:4]), month=int(last[5:7]), day=int(last[8:10])), info, videos, vhist, hist)


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
        KEY = load_key()
        check() if "--check" in sys.argv else collect()
