#!/usr/bin/env python3
"""떡상 후보 발굴기 — 채널 체급 대비 비정상적으로 빨리 크는 영상을 찾는다.

기준(2026-09-20 사용자 확정):
  · 구독자 100만 채널이 100만 조회 낸 건 평범하다. 구독자 3천 채널이 이틀 만에 30만 낸 게 진짜다.
  · 그래서 절대 조회수가 아니라 **배수**(그 채널 평소 대비)와 **속도**(시간당 조회수)를 같이 본다.
  · 24시간에 3만과 20일에 30만은 완전히 다른 얘기다.

배수 기준선은 그 채널 최근 10편의 **중간값**을 쓴다(평균은 대박 한 편에 끌려 올라가 배수가 작아진다).

할당량 설계 — 유튜브 API는 하루 10,000유닛, 검색 1회가 100유닛이라 검색만으론 금방 바닥난다.
  1) 인기 차트(videos.chart=mostPopular)   1유닛   — 거의 공짜, 큰 채널 위주
  2) 키워드 검색(search.list)            100유닛   — 작은 채널 발굴용, 키워드를 돌아가며 조금씩
  3) **채널 풀 재확인**                  채널당 2유닛 — 한 번 발견한 채널은 계속 싸게 본다
  3번이 핵심이다. 돌릴수록 풀이 커져서 검색 없이도 감시 범위가 넓어진다.

쓰기:
  python3 발굴.py               # 기본 예산(3,000유닛)으로 수집 → outliers.json
  python3 발굴.py --budget 1500 # 예산 지정
  python3 발굴.py --pool        # 채널 풀 현황만 보기
키: 같은 폴더 .env 의 YOUTUBE_API_KEY (값은 절대 출력하지 않음)
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
DATA = ROOT / "data"          # 깃허브 액션이 gh-pages로 보존하는 폴더
KST = timezone(timedelta(hours=9))
API = "https://www.googleapis.com/youtube/v3/"

SHORT_MAX_SEC = 180          # 3분 이하 = 쇼츠로 본다
MAX_AGE_H = 24 * 14          # 2주 넘은 영상은 '지금 터지는 중'이 아니다
MIN_VIEWS = 3000             # 이보다 적으면 아직 신호가 아니다
MIN_MULTIPLE = 3             # 채널 평소의 3배 미만은 후보에서 뺀다
TOP_N = 50
POOL_RECHECK_H = 20          # 채널 기준선(중간값)을 다시 재는 주기
POOL_MAX_SUBS = 2_000_000    # 이보다 큰 채널은 풀에서 감시하지 않는다(체급 대비가 의미 없음)
MAX_VIDEO_COUNT = 3000       # 영상이 이보다 많으면 방송사·언론사 클립 채널로 본다
GROWTH_MIN_SUBS = 300        # 구독자 급상승 목록에 넣을 최소 구독자
GROWTH_TOP_N = 50

# 검색 씨앗 — 한 번에 다 돌리지 않고 돌아가며 조금씩 쓴다. 자유롭게 고쳐도 된다.
SEEDS = [
    "이유", "진짜 이유", "충격", "실화", "역대급", "레전드", "소름", "몰랐던",
    "알고보니", "하루만에", "정체", "비밀", "이것만", "총정리", "결국",
    "공학", "과학", "역사", "경제", "부동산", "재테크", "건강", "심리",
    "자동차", "항공", "선박", "건설", "우주", "동물", "음식", "여행",
    "사건", "사고", "실험", "리뷰", "정리", "썰", "근황", "논란",
]
CATEGORIES = ["1", "2", "10", "15", "17", "19", "20", "22", "23", "24", "25", "26", "27", "28"]

KEY = None
USED = 0                     # 이번 실행에서 쓴 할당량(유닛)


def env_value(name):
    val = os.environ.get(name, "").strip()
    env = ROOT / ".env"
    if not val and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                val = line.split("=", 1)[1].strip()
    return val


def get(method, cost=1, **params):
    """API 호출. cost는 유닛(검색 100, 나머지 1)."""
    global USED
    url = API + method + "?" + urllib.parse.urlencode({**params, "key": KEY})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                USED += cost
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            if e.code == 403 and "quota" in body.lower():
                raise SystemExit(f"✘ API 할당량 소진 (이번 실행 {USED}유닛). 내일 다시 돌거나 예산을 줄이세요.")
            if e.code in (500, 503) and attempt < 2:
                time.sleep(2 * (attempt + 1)); continue
            print(f"  ! {method} 실패 {e.code}", file=sys.stderr)
            return {}
        except Exception:
            if attempt < 2:
                time.sleep(2 * (attempt + 1)); continue
            return {}
    return {}


def load(name, default):
    p = DATA / name
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def save(name, obj):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


HANGUL = re.compile(r"[\uac00-\ud7a3]")


def blocklist():
    cfg = {}
    p = ROOT / "발굴_제외.json"
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    words = [w.lower() for w in cfg.get("회사_방송사", [])]
    return words, set(cfg.get("제외_채널ID", [])), [n.lower() for n in cfg.get("제외_채널이름", [])]


BLOCK_WORDS, BLOCK_IDS, BLOCK_NAMES = [], set(), []


def is_korean(v, c):
    """국내 채널만. 나라가 한국이 아니라고 적혀 있으면 빼고, 한글이 하나도 없으면 뺀다."""
    if c.get("country") and c["country"] != "KR":
        return False
    return bool(HANGUL.search(v["title"]) or HANGUL.search(c.get("title", "")))


def is_personal(c):
    """일반인 채널만. 방송사·기업·언론 이름이 들어갔거나 영상이 너무 많으면 뺀다."""
    if c["id"] in BLOCK_IDS:
        return False
    name = (c.get("title") or "").lower()
    if any(n and n in name for n in BLOCK_NAMES):
        return False
    if any(w and w in name for w in BLOCK_WORDS):
        return False
    if (c.get("video_count") or 0) > MAX_VIDEO_COUNT:
        return False
    return True


def parse_time(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def dur_sec(d):
    h = int(re.search(r"(\d+)H", d).group(1)) if "H" in d else 0
    m = int(re.search(r"(\d+)M", d).group(1)) if "M" in d else 0
    s = int(re.search(r"(\d+)S", d).group(1)) if "S" in d else 0
    return h * 3600 + m * 60 + s


def chunks(seq, n=50):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def video_rows(ids):
    """영상 id들 → 기본 정보. 50개당 1유닛."""
    out = {}
    for part in chunks(ids, 50):
        for v in get("videos", part="snippet,statistics,contentDetails", id=",".join(part)).get("items", []):
            st, sn = v.get("statistics", {}), v["snippet"]
            if sn.get("liveBroadcastContent") in ("live", "upcoming"):
                continue                      # 라이브·예정은 길이가 없고 조회수 의미도 다르다
            dur = v.get("contentDetails", {}).get("duration")
            if not dur:
                continue
            out[v["id"]] = {
                "id": v["id"], "title": sn["title"], "ch": sn["channelTitle"], "ch_id": sn["channelId"],
                "published": sn["publishedAt"], "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)), "comments": int(st.get("commentCount", 0)),
                "sec": dur_sec(dur),
                "thumb": (sn.get("thumbnails", {}).get("medium") or sn.get("thumbnails", {}).get("default") or {}).get("url", ""),
            }
    return out


def channel_rows(ids):
    """채널 id들 → 구독자·업로드 재생목록. 50개당 1유닛."""
    out = {}
    for part in chunks(ids, 50):
        for c in get("channels", part="snippet,statistics,contentDetails", id=",".join(part)).get("items", []):
            st = c.get("statistics", {})
            out[c["id"]] = {
                "id": c["id"], "title": c["snippet"]["title"],
                "subs": None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0)),
                "uploads": c["contentDetails"]["relatedPlaylists"]["uploads"],
                "total_views": int(st.get("viewCount", 0)), "video_count": int(st.get("videoCount", 0)),
                "country": c["snippet"].get("country"), "started": c["snippet"].get("publishedAt", "")[:10],
            }
    return out


def recent_uploads(uploads, n=12):
    """업로드 재생목록에서 최근 n개 영상 id. 1유닛."""
    r = get("playlistItems", part="contentDetails", playlistId=uploads, maxResults=n)
    return [i["contentDetails"]["videoId"] for i in r.get("items", [])]


def baseline(rows, exclude_id=None):
    """그 채널 평소 조회수 = 최근 영상 중간값. 쇼츠/본편을 섞지 않고 각각 따로 잰다."""
    out = {}
    for short in (True, False):
        vals = [v["views"] for v in rows
                if (v["sec"] <= SHORT_MAX_SEC) == short and v["id"] != exclude_id]
        out["s" if short else "l"] = round(statistics.median(vals)) if vals else None
    return out


def track_subs(pool, now):
    """풀 전체 구독자를 다시 재서 이력에 남긴다. 50곳당 1유닛이라 아주 싸다."""
    ids = list(pool)
    for cid, c in channel_rows(ids).items():
        cur = pool.setdefault(cid, {})
        cur.update(c)
        hist = cur.setdefault("subs_hist", [])
        today = now.astimezone(KST).strftime("%Y-%m-%d %H")
        if c["subs"] is not None and (not hist or hist[-1][0] != today):
            hist.append([today, c["subs"]])
            del hist[:-60]


def growing(pool, now):
    """구독자가 빨리 느는 일반인 국내 채널. 이력이 2개 이상 쌓여야 계산된다."""
    out = []
    for c in pool.values():
        hist = c.get("subs_hist") or []
        if len(hist) < 2 or c.get("subs") is None or c["subs"] < GROWTH_MIN_SUBS:
            continue
        if not is_personal(c) or (c.get("country") and c["country"] != "KR"):
            continue
        if not HANGUL.search(c.get("title") or ""):
            continue
        t0 = datetime.strptime(hist[0][0], "%Y-%m-%d %H").replace(tzinfo=KST)
        t1 = datetime.strptime(hist[-1][0], "%Y-%m-%d %H").replace(tzinfo=KST)
        days = max((t1 - t0).total_seconds() / 86400, 1 / 24)
        gain = hist[-1][1] - hist[0][1]
        if gain <= 0:
            continue
        per_day = gain / days
        out.append({**{k: c.get(k) for k in ("id", "title", "subs", "video_count", "started", "country")},
                    "gain": gain, "days": round(days, 1), "per_day": round(per_day),
                    "pct_day": round(100 * per_day / max(hist[0][1], 1), 2),
                    "base": c.get("base") or {},
                    "url": f"https://www.youtube.com/channel/{c['id']}"})
    for r in out:
        r["score"] = round(r["per_day"] ** 0.5 * max(r["pct_day"], 0.01) ** 0.5, 1)
    return sorted(out, key=lambda r: -r["score"])[:GROWTH_TOP_N]


def discover(budget, pool):
    """후보 영상 id를 모은다. 싼 것부터 쓰고 예산이 남으면 검색으로 넓힌다."""
    found, notes = set(), []

    # 1) 인기 차트 — 1유닛씩
    for cat in CATEGORIES:
        if USED + 1 > budget:
            break
        r = get("videos", part="id", chart="mostPopular", regionCode="KR", videoCategoryId=cat, maxResults=50)
        found.update(i["id"] for i in r.get("items", []))
    notes.append(f"인기차트 {len(found)}개")

    # 2) 채널 풀 재확인 — 채널당 1유닛. 발견해 둔 채널이 많을수록 싸게 넓어진다.
    before = len(found)
    watch = [c for c in pool.values() if (c.get("subs") or 0) <= POOL_MAX_SUBS]
    watch.sort(key=lambda c: c.get("last_seen", ""))          # 오래 안 본 채널부터
    for c in watch:
        if USED + 2 > budget * 0.20:                          # 풀 재확인은 예산의 20%까지
            break
        found.update(recent_uploads(c["uploads"], 6))
        c["last_seen"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    notes.append(f"채널풀 {len(found) - before}개(감시 {len(watch)}곳)")

    # 3) 키워드 검색 — 100유닛씩. 새 채널을 풀에 넣는 유일한 통로라 매번 조금씩 쓴다.
    before = len(found)
    after = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds").replace("+00:00", "Z")
    state = load("hunt_state.json", {"seed": 0})
    used_seeds = []
    while USED + 100 <= budget * 0.40:                        # 검색은 40% 선까지
        kw = SEEDS[state["seed"] % len(SEEDS)]
        state["seed"] += 1
        used_seeds.append(kw)
        r = get("search", cost=100, part="id", type="video", q=kw, order="viewCount",
                publishedAfter=after, regionCode="KR", relevanceLanguage="ko", maxResults=50)
        found.update(i["id"]["videoId"] for i in r.get("items", []) if i.get("id", {}).get("videoId"))
        if len(used_seeds) >= 6:
            break
    save("hunt_state.json", state)
    notes.append(f"검색 {len(found) - before}개(키워드 {', '.join(used_seeds) or '없음'})")
    return found, notes


def hunt(budget):
    global BLOCK_WORDS, BLOCK_IDS, BLOCK_NAMES
    BLOCK_WORDS, BLOCK_IDS, BLOCK_NAMES = blocklist()
    now = datetime.now(timezone.utc)
    pool = load("hunt_channels.json", {})
    ids, notes = discover(budget, pool)
    print(f"· 후보 영상 {len(ids)}개 — " + " / ".join(notes))

    vids = video_rows(ids)
    # 나이·조회수로 먼저 거른다(여기서 대부분 빠진다)
    live = {}
    for vid, v in vids.items():
        age = (now - parse_time(v["published"])).total_seconds() / 3600
        if age <= 0 or age > MAX_AGE_H or v["views"] < MIN_VIEWS:
            continue
        v["age_h"] = round(age, 1)
        live[vid] = v
    print(f"· 살아있는 후보 {len(live)}개 (2주 이내 · {MIN_VIEWS:,}회 이상)")

    # 채널 정보 — 풀에 없는 채널만 새로 받는다(50곳당 1유닛)
    need = {v["ch_id"] for v in live.values()}
    for cid, c in channel_rows([c for c in need if c not in pool]).items():
        pool.setdefault(cid, {}).update(c)

    # 기준선(최근 영상 중간값)은 채널당 2유닛이라 예산 안에서만. 유망한 채널부터 잰다.
    promise = {}
    for v in live.values():
        promise[v["ch_id"]] = max(promise.get(v["ch_id"], 0), v["views"] / max(v["age_h"], 1))
    todo = [cid for cid in need
            if pool.get(cid, {}).get("uploads")
            and (pool[cid].get("subs") or 0) <= POOL_MAX_SUBS
            and (now - parse_time(pool[cid].get("based_at", "1970-01-01T00:00:00+00:00"))).total_seconds() / 3600 > POOL_RECHECK_H]
    todo.sort(key=lambda cid: -promise.get(cid, 0))
    measured = 0
    for cid in todo:
        if USED + 3 > budget - 40:            # 구독자 추적(풀 전체) 몫 40유닛은 남긴다
            break
        c = pool[cid]
        rows = list(video_rows(recent_uploads(c["uploads"], 12)).values())
        if rows:
            c["base"] = baseline(rows)
            c["based_at"] = now.isoformat(timespec="seconds")
            measured += 1
    track_subs(pool, now)
    save("hunt_channels.json", pool)
    print(f"· 채널 기준선 {measured}곳 측정 (대기 {max(0, len(todo) - measured)}곳 — 다음 실행에서)")

    # 점수 매기기 — 국내 일반인 채널만
    rows, cut = [], {"외국": 0, "회사": 0}
    for v in live.values():
        c = pool.get(v["ch_id"])
        if not c or not c.get("base"):
            continue
        if not is_korean(v, c):
            cut["외국"] += 1; continue
        if not is_personal(c):
            cut["회사"] += 1; continue
        short = v["sec"] <= SHORT_MAX_SEC
        base = c["base"]["s" if short else "l"]
        if not base:
            continue
        mult = v["views"] / max(base, 1)
        if mult < MIN_MULTIPLE:
            continue
        rows.append({**v, "short": short, "subs": c.get("subs"), "base": base,
                     "mult": round(mult, 1), "vph": round(v["views"] / max(v["age_h"], 1)),
                     "url": f"https://www.youtube.com/{'shorts/' if short else 'watch?v='}{v['id']}",
                     "ch_url": f"https://www.youtube.com/channel/{v['ch_id']}"})

    # 배수 순위와 속도 순위를 반반 섞는다 — 절대 조회수가 아니라 '이상함 + 빠름'
    def ranked(group):
        if not group:
            return []
        by_mult = {r["id"]: i for i, r in enumerate(sorted(group, key=lambda r: -r["mult"]))}
        by_vph = {r["id"]: i for i, r in enumerate(sorted(group, key=lambda r: -r["vph"]))}
        n = len(group)
        for r in group:
            r["score"] = round(100 * (1 - (by_mult[r["id"]] + by_vph[r["id"]]) / (2 * max(n - 1, 1))), 1)
        return sorted(group, key=lambda r: -r["score"])[:TOP_N]

    shorts = ranked([r for r in rows if r["short"]])
    longs = ranked([r for r in rows if not r["short"]])
    chans = growing(pool, now)
    print(f"· 걸러냄 — 외국 {cut['외국']}편 · 회사/방송사 {cut['회사']}편")
    out = {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "used": USED, "budget": budget,
           "pool": len(pool), "scanned": len(live), "notes": notes,
           "rules": {"max_age_h": MAX_AGE_H, "min_views": MIN_VIEWS, "min_mult": MIN_MULTIPLE,
                     "short_max_sec": SHORT_MAX_SEC},
           "shorts": shorts, "long": longs, "channels": chans, "cut": cut}
    save("outliers.json", out)
    print(f"✔ 쇼츠 {len(shorts)}편 · 본편 {len(longs)}편 · 급상승채널 {len(chans)}곳 저장 (outliers.json) · {USED}유닛 사용 · 채널풀 {len(pool)}곳")
    for r in (shorts[:3] + longs[:3]):
        print(f"   {r['mult']:>5.1f}배 {r['vph']:>7,}/h  {r['ch'][:12]:<12} 구독 {(r['subs'] or 0):>9,}  {r['title'][:34]}")


if __name__ == "__main__":
    if "--pool" in sys.argv:
        pool = load("hunt_channels.json", {})
        print(f"채널 풀 {len(pool)}곳")
        for c in sorted(pool.values(), key=lambda c: -(c.get("subs") or 0))[:30]:
            b = c.get("base") or {}
            print(f"  구독 {(c.get('subs') or 0):>10,}  쇼츠중간 {str(b.get('s')):>8}  본편중간 {str(b.get('l')):>8}  {c.get('title','')[:24]}")
        raise SystemExit
    KEY = env_value("YOUTUBE_API_KEY")
    if not KEY:
        sys.exit("YOUTUBE_API_KEY가 없습니다 (.env 또는 환경변수)")
    budget = 3000
    if "--budget" in sys.argv:
        budget = int(sys.argv[sys.argv.index("--budget") + 1])
    hunt(budget)
