#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""소재 추천기 — 하루 2번(한국시간 07·15시, 맥 launchd) '조회수 터질 만한 소재'를 AI가 판단해 대시보드 🎯 소재 탭에 올린다.

2026-09-26 사용자: "대시보드 시장조사를 하루 2번씩 조회수 빵빵 터질 만한 소재를 판단해서 가져오게" → 거대한비밀·거인의무덤, 내 맥, 07·15시.
2026-09-27 사용자: "새 영어채널도, 5개 말고 20개씩, 너무 똑같은 주제만 나오고 최신 이슈 반영이 안 된다"
  → The Korea Paradox 추가 · 채널당 20개 · 뉴스 빙(최신순)+구글(최근 14일) · 구글 트렌드 · 영어권 한국 영상(유튜브 RSS)
    · 최근 추천에 자주 나온 대상 억제 + 같은 대상 2개까지 · 근거 기사 날짜로 📰 최신 표시.

입력(판단 재료 — 전부 프로그램이 모은다, AI 토큰 0):
  · 발굴 결과(한국어 채널): gh-pages 의 data/outliers.json (발굴.py 가 06·14·21시에 찾은 '채널 평소보다 몇 배 빨리 크는 영상')
  · 영어권 한국 영상(영어 채널): 소재추천_영어재료.json 의 채널을 유튜브 RSS(할당량 0)로 훑어 평소 대비 배수·하루 조회수 + 최근 공급
  · 우리 채널 성적: gh-pages 의 data/videos.json (무엇이 터졌고 무엇이 멈췄나)
  · 이미 만든 편: 각 채널 episodes 폴더 이름 (반복 금지). 폴더를 못 보는 예약 실행은 topics/done.json 사본
  · 최근 추천: topics/history.jsonl — 최근 추천 소재 + 자주 나온 대상(최근 8번 중 몇 번)
  · 최신 뉴스: 빙 뉴스(최신순) + 구글 뉴스(최근 14일) RSS 를 합쳐 키워드마다 가장 최근 기사, 최근 30일만 (키워드는 소재추천_기준.json)
  · 지금 뜨는 검색어: 구글 트렌드 한국 일간 급상승(검색어 + 관련 기사)
  · 채널 공식·점수 기준: 소재추천_기준.json (사용자 확정 기준을 그대로 옮김, 바뀌면 이 파일만 고친다)
판단: `claude -p`(구독 안에서) — 채널마다 1번. 대상 제한으로 빠질 몫까지 2개 더 받는다.
토큰 절약(2026-09-27 사용자: "성능은 유지하면서 토큰을 최대한 적게"):
  · claude 기본 지시문·도구·MCP(openchrome·higgsfield)·플러그인·스킬을 빼고 짧은 지시문 하나로 부른다(LEAN — 호출마다 붙던 군더더기).
  · 재료는 JSON 대신 표 줄로, 긴 주소는 R번호로 보낸다(답의 R번호는 프로그램이 주소로 되돌린다).
  · 답도 JSON 대신 줄 형식. 위에서 detail_top 개만 제작 메모(첫문장·장면·확인·위험)까지, 나머지는 제목·이유·근거만.
  · 토큰 사용량을 로그와 latest.json(tokens)에 남긴다.
뒤처리(프로그램): 지어낸 근거 주소 버림 · 같은 대상 2개까지(최근 3번 이상 나온 대상은 1개) · 근거 기사 날짜로 '최신' 표시.
출력: topics/latest.json (대시보드), topics/history.jsonl (나중에 추천 vs 실제 조회수 맞춰 보기)

쓰기:
  python3 소재추천.py                    # 모든 채널
  python3 소재추천.py --channel 거대한비밀
  python3 소재추천.py --dry              # 재료만 모아 topics/_prompt_채널.txt · _materials_채널.json 저장(AI 안 부름)
  python3 소재추천.py --answers 폴더 [--label 이름]
                                        # claude 를 못 쓸 때(구독 한도 등): --dry 재료 + 폴더/채널.txt(같은 줄 형식 답, 또는 .json)로 마무리
  python3 소재추천.py --score-only       # 우리 영상 채점·정확도 보정만
  python3 소재추천.py --done-only        # 편 폴더를 읽어 topics/done.json 만 갱신(데스크톱에서 — 비용_자동갱신.sh 가 편마다 부름)
"""
import html
import json
import math
import random
import re
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "topics"
KST = timezone(timedelta(hours=9))
CFG = json.loads((ROOT / "소재추천_기준.json").read_text(encoding="utf-8"))
_EN = ROOT / "소재추천_영어재료.json"
EN_CONF = json.loads(_EN.read_text(encoding="utf-8")) if _EN.exists() else {}
VIDEOS, VIEWS = None, None   # gh-pages 의 우리 영상 목록·일별 조회수(main 에서 한 번 읽음)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
NEWS_DAYS = 30     # 이보다 오래된 기사는 재료에서 뺀다
FRESH_DAYS = 14    # 이 안의 기사·검색어에 근거하면 '최신' 소재(📰)
RECENT_RUNS = 8    # 자주 나온 대상을 셀 때 보는 최근 추천 횟수(하루 2번 → 4일)
OFTEN_MAX = 3      # 최근 추천에서 이만큼 이상 나온 대상은 이번에 1개까지만
EXTRA = 2          # 대상 제한으로 빠질 몫까지 몇 개 더 받는다
RSS_CACHE = OUT / "_rss_cache.json"
EN_MIN_MULT = 1.5  # 영어권 한국 영상: 그 채널 평소의 이만큼 이상이어야 '빨리 크는 영상'
HANGUL = re.compile(r"[\uac00-\ud7a3]")
# 뉴스에서 뺄 것: 블로그·카페·영상 주소, 도박·연재물 광고성 글(2026-09-27 최신순으로만 뽑았더니 섞여 들어옴)
NEWS_BLOCK_HOSTS = ("blog.naver.com", "cafe.naver.com", "post.naver.com", "tistory.com", "brunch.co.kr", "blog.daum.net",
                    "velog.io", "youtube.com", "instagram.com", "facebook.com", "x.com", "twitter.com")
NEWS_SPAM = re.compile(r"슬롯|카지노|토토|바카라|먹튀|19금|블로그|\d+화\b")
KOREA_RE = re.compile(r"korea|seoul|busan|samsung|hyundai|k-?pop|k-?drama|chaebol|pyongyang|kim jong|jeju|gangnam|hynix|coupang|"
                      r"kakao|naver|hanwha|\bkia\b|\bbts\b|blackpink|squid game|hangul|suneung|hagwon", re.I)


def log(*a):
    print(datetime.now(KST).strftime("%m-%d %H:%M:%S"), *a, flush=True)


def fresh_cut():
    return (datetime.now(KST) - timedelta(days=FRESH_DAYS)).strftime("%Y-%m-%d")


def gh_json(name):
    """대시보드가 쌓아 둔 기록(gh-pages 브랜치 data/)을 읽는다. main 의 data/ 는 비어 있다."""
    try:
        raw = subprocess.run(["git", "show", f"origin/gh-pages:data/{name}"], cwd=ROOT, capture_output=True, check=True).stdout
        return json.loads(raw)
    except Exception as e:
        log("gh-pages 읽기 실패", name, str(e)[:120])
        return None


def fetch(url, timeout=20):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read().decode("utf-8", "ignore")


def _tag(x, tag):
    """XML 조각에서 <tag ...>값</tag> 하나(CDATA·HTML 이스케이프를 풀어서)."""
    m = re.search(rf"<{tag}(?:\s[^>]*)?>(.*?)</{tag}>", x, re.S)
    v = (m.group(1) if m else "").strip()
    if v.startswith("<![CDATA[") and v.endswith("]]>"):
        v = v[9:-3]
    return html.unescape(v).strip()


class Refs:
    """긴 주소 → 짧은 번호(R1, R2 …). 재료의 약 40%가 주소였다(2026-09-27 측정). 답에 적힌 번호는 원래 주소로 되돌린다."""
    def __init__(self):
        self.by_id, self.by_url = {}, {}

    def __call__(self, url):
        if not url:
            return "-"
        if url not in self.by_url:
            k = f"R{len(self.by_url) + 1}"
            self.by_url[url], self.by_id[k] = k, url
        return self.by_url[url]


# ---- 재료를 표 줄로(JSON 은 칸 이름이 줄마다 되풀이돼 토큰이 많다)

def sec_outliers(ob, R):
    L = [f"기준 {ob.get('기준시각')} · 칸: 번호|종류|평소대비(배)|조회|시간당|경과일|채널(구독)|제목"]
    for k in ("쇼츠", "본편"):
        L += [f"{R(r['url'])}|{k}|{r['평소대비']}|{r['조회']}|{r['시간당']}|{r['경과일']}|{r['채널']}({r['구독']})|{r['제목']}" for r in ob.get(k, [])]
    if ob.get("뜨는채널"):
        L.append("구독자가 빨리 느는 채널 · 칸: 번호|채널|구독|하루 증가")
        L += [f"{R(r['url'])}|{r['채널']}|{r['구독']}|{r['하루증가']}" for r in ob["뜨는채널"]]
    return "\n".join(L)


def sec_en(eo, R):
    L = [f"기준 {eo['기준시각']} · 훑은 채널 {eo['훑은_채널']} · 칸: 번호|종류|평소대비(배)|하루조회|경과일|채널|제목"]
    L += [f"{R(r['url'])}|{r['종류']}|{r['평소대비']}|{r['하루조회']}|{r['경과일']}|{r['채널']}|{r['제목']}" for r in eo["뜨는_영어권_한국영상"]]
    L.append("최근 60일 영어권 한국 본편(공급 — 같은 각도가 이미 있나) · 칸: 번호|경과일|조회|채널|제목")
    L += [f"{R(r.get('url'))}|{r['경과일']}|{r['조회']}|{r['채널']}|{r['제목']}" for r in eo["최근60일_영어권_한국본편(공급)"]]
    L.append("주제별 영어권 수요·공급(2026-09-26 조사) · 칸: 주제|최근12개월 편수|그중 10만+|100만+|최근24개월 최고")
    L += [f"{r['주제']}|{r['최근12개월_편수']}|{r['그중_10만이상']}|{r['최근12개월_100만이상']}|{r['최근24개월_최고']}"
          for r in eo["주제별_영어권_수요공급(2026-09-26 조사)"]]
    return "\n".join(L)


def sec_ours(o, R):
    if not o["편수"]:
        return "아직 올린 영상 없음"
    row = lambda r: f"{R(r['url'])}|{r['조회']}|{'쇼츠' if r['쇼츠'] else '본편'}|{r['경과일']}|{r['제목']}"
    return "\n".join([f"올린 영상 {o['편수']}편 · 칸: 번호|조회|종류|경과일|제목", "잘된 영상:"] + [row(r) for r in o["잘된_영상"]]
                     + ["안된 영상:"] + [row(r) for r in o["안된_영상"]])


def sec_done(d):
    t = [re.sub(r"\s+", " ", re.sub(r"#\S+", "", x)).strip()[:45] for x in d["올린_영상_제목"]]
    return "편 폴더: " + (" / ".join(d["편_폴더"]) or "없음") + "\n올린 영상 제목: " + (" / ".join(t) or "없음")


def sec_recent(rec):
    often = ", ".join(f"{x['대상']}({x['나온_횟수']}번)" for x in rec["자주_나온_대상"]) or "없음"
    return f"최근 {rec['살펴본_추천_횟수']}번 추천에 자주 나온 대상: {often}\n최근 추천 소재: " + (" / ".join(rec["최근_추천_소재"]) or "없음")


def sec_news(items, R):
    if not items:
        return "없음"
    L = ["검색어별 · 칸: 번호|날짜|제목 ~ 요약"]
    for kw in dict.fromkeys(r["검색어"] for r in items):   # 최신 기사가 있는 검색어부터
        L.append(f"[{kw}]")
        L += [f"{R(r['url'])}|{r['날짜'][5:]}|{r['제목']}" + (f" ~ {r['요약']}" if r.get("요약") else "") for r in items if r["검색어"] == kw]
    return "\n".join(L)


def sec_trend(trend, R):
    return "\n".join(f"{t['검색어']}({t['검색량']}): " + " / ".join(f"{R(a['url'])} {a['제목']}" for a in t["기사"] if a.get("url"))
                     for t in trend) or "없음"


# ---------------------------------------------------------------- 재료: 유튜브

def outliers_brief():
    o = gh_json("outliers.json") or {}
    def vid(r):
        return {"제목": r.get("title"), "채널": r.get("ch"), "구독": r.get("subs"), "조회": r.get("views"),
                "평소대비": r.get("mult"), "시간당": r.get("vph"), "경과일": round((r.get("age_h") or 0) / 24, 1), "url": r.get("url")}
    top = lambda xs, n: sorted(xs or [], key=lambda r: -(r.get("score") or 0))[:n]
    return {"기준시각": o.get("at"),
            "쇼츠": [vid(r) for r in top(o.get("shorts"), 30)],
            "본편": [vid(r) for r in top(o.get("long"), 20)],
            "뜨는채널": [{"채널": r.get("title"), "구독": r.get("subs"), "하루증가": r.get("per_day"), "url": r.get("url")} for r in top(o.get("channels"), 12)]}


def _yt_feed(cid, tries=5):
    """유튜브 채널 RSS — 최근 15편(제목·올린 시각·조회수·쇼츠 여부). API 할당량을 쓰지 않는다.
    RSS 는 같은 채널도 404·500 을 무작위로 돌려줘서(2026-09-27 확인: 5번 중 1~4번 실패) 몇 번 다시 묻는다."""
    for i in range(tries):
        try:
            x = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}", timeout=15)
            break
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(0.8 + random.random())
    name = _tag(x.split("<entry>")[0], "title")
    rows = []
    for e in re.findall(r"<entry>(.*?)</entry>", x, re.S):
        vid = _tag(e, "yt:videoId")
        link = (re.search(r'<link rel="alternate" href="([^"]+)"', e) or [None, ""])[1]
        views = re.search(r'<media:statistics views="(\d+)"', e)
        try:
            pub = datetime.fromisoformat(_tag(e, "published"))
        except Exception:
            continue
        rows.append({"id": vid, "title": _tag(e, "title"), "pub": pub, "views": int(views.group(1)) if views else 0,
                     "short": "/shorts/" in link, "url": link or f"https://www.youtube.com/watch?v={vid}"})
    return name, rows


def en_outliers(conf, days=30, top=25):
    """영어권 한국 영상 — 벤치마크 채널을 RSS 로 훑는다. 발굴.py 와 같은 생각: 절대 조회수가 아니라
    그 채널 평소(최근 영상 중간값, 쇼츠·본편 따로) 대비 배수 + 속도(하루 조회수). 최근 60일 한국 본편은 '공급'으로 따로 준다."""
    now = datetime.now(timezone.utc)

    def run(ch):
        try:
            return ch, _yt_feed(ch["id"])
        except Exception:
            return ch, None

    chans = conf.get("rss_channels", [])
    with ThreadPoolExecutor(4) as ex:
        got = list(ex.map(run, chans))
    # RSS 가 막힌 채널은 마지막 성공분(3일 이내)을 쓴다 — 조회수·경과일은 그때 받은 시각 기준(2026-09-27: 한 시간에 여러 번 부르면 59곳 중 19곳만 열림)
    try:
        cache = json.loads(RSS_CACHE.read_text(encoding="utf-8")) if RSS_CACHE.exists() else {}
    except Exception:
        cache = {}
    feeds, live, old = [], 0, 0
    for ch, res in got:
        if res and res[1]:
            live += 1
            cache[ch["id"]] = {"at": now.isoformat(), "name": res[0], "rows": [{**r, "pub": r["pub"].isoformat()} for r in res[1]]}
            feeds.append((ch, res[0], res[1], now))
        elif ch["id"] in cache and now - datetime.fromisoformat(cache[ch["id"]]["at"]) < timedelta(days=3):
            c0 = cache[ch["id"]]; old += 1
            feeds.append((ch, c0["name"], [{**r, "pub": datetime.fromisoformat(r["pub"])} for r in c0["rows"]], datetime.fromisoformat(c0["at"])))
    try:
        RSS_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    cand, supply = [], []
    for ch, name, rows, seen_at in feeds:
        for r in rows:
            r["age_d"] = max((seen_at - r["pub"]).total_seconds() / 86400, 0.25)
        for r in rows:
            if not KOREA_RE.search(r["title"]):
                continue
            same = [x["views"] for x in rows if x["short"] == r["short"] and x["id"] != r["id"] and x["age_d"] >= 3]
            base = statistics.median(same) if len(same) >= 3 else None
            row = {"제목": r["title"], "채널": name or ch.get("name"), "종류": "쇼츠" if r["short"] else "본편", "조회": r["views"],
                   "평소대비": round(r["views"] / max(base, 1), 1) if base else None, "하루조회": round(r["views"] / r["age_d"]),
                   "경과일": round(r["age_d"], 1), "url": r["url"]}
            if not r["short"] and r["age_d"] <= 60:
                supply.append({"제목": r["title"], "채널": row["채널"], "경과일": round(r["age_d"]), "조회": r["views"], "url": r["url"]})
            if r["age_d"] <= days and row["평소대비"] and row["평소대비"] >= EN_MIN_MULT:
                cand.append(row)
    if cand:   # 배수 순위와 속도 순위를 반반(발굴.py 와 같은 방식)
        bm = {id(r): i for i, r in enumerate(sorted(cand, key=lambda r: -r["평소대비"]))}
        bv = {id(r): i for i, r in enumerate(sorted(cand, key=lambda r: -r["하루조회"]))}
        n = max(len(cand) - 1, 1)
        for r in cand:
            r["점수"] = round(100 * (1 - (bm[id(r)] + bv[id(r)]) / (2 * n)), 1)
        cand.sort(key=lambda r: -r["점수"])
    supply.sort(key=lambda r: r["경과일"])
    return {"기준시각": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "훑은_채널": f"{live}/{len(chans)}" + (f" (+지난 성공분 {old})" if old else ""),
            "뜨는_영어권_한국영상": cand[:top], "최근60일_영어권_한국본편(공급)": supply[:40],
            "주제별_영어권_수요공급(2026-09-26 조사)": conf.get("supply", [])}


def ours_brief(ch):
    v = VIDEOS or {}
    now = datetime.now(timezone.utc)
    rows = []
    for vid, r in v.items():
        if r.get("ch") != ch or not r.get("public", True):
            continue
        try:
            days = (now - datetime.fromisoformat(r["published"].replace("Z", "+00:00"))).total_seconds() / 86400
        except Exception:
            days = None
        rows.append({"제목": r.get("title"), "조회": r.get("views") or 0, "쇼츠": bool(r.get("short")),
                     "경과일": round(days, 1) if days is not None else None,
                     "url": f"https://www.youtube.com/shorts/{vid}" if r.get("short") else f"https://www.youtube.com/watch?v={vid}"})
    rows.sort(key=lambda r: -r["조회"])
    return {"잘된_영상": rows[:8], "안된_영상": [r for r in rows if (r["경과일"] or 0) >= 2][-6:], "편수": len(rows)}


# ---------------------------------------------------------------- 재료: 이미 만든 편 · 최근 추천

def scan_done(c):
    """편 폴더 이름 → topics/done.json 사본. 예약 실행(launchd)은 맥 보안상 데스크톱을 못 읽어서 ~/.sojae 사본 저장소에서 돈다
    → 폴더가 안 보이면 사본을 쓴다. 사본은 데스크톱에서 돌 때(편 하나 끝날 때 비용_자동갱신.sh 가 --done-only 로 부름) 갱신된다."""
    names, seen_dirs = [], False
    for d in c["episodes"]:
        p = (ROOT / d).resolve()
        try:
            if p.is_dir():
                names += [re.sub(r"^\d+[-_ ]*", "", x.name).replace("_", " ") for x in sorted(p.iterdir()) if x.is_dir() and re.match(r"^\d", x.name)]
                seen_dirs = True
        except PermissionError:
            pass
    dp = OUT / "done.json"
    done = json.loads(dp.read_text(encoding="utf-8")) if dp.exists() else {}
    if not seen_dirs:
        return done.get(c["name"], [])
    new = sorted(set(names))
    if done.get(c["name"]) != new:   # 바뀔 때만 쓴다(비용_자동갱신.sh 가 git diff 로 올릴지 정함)
        done[c["name"]] = new
        OUT.mkdir(exist_ok=True)
        dp.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    return new


def done_topics(c):
    """이미 만든 편 — ① 편 폴더(또는 done.json 사본) ② 우리 채널에 올라간 영상 제목."""
    titles = [r.get("title") for r in (VIDEOS or {}).values() if r.get("ch") == c["name"] and r.get("title")]
    return {"편_폴더": scan_done(c), "올린_영상_제목": titles[:80]}


def _target_name(t):
    """추천 하나의 '대상'(건물·기업·인물·장소). AI가 적은 대상 칸, 없으면(예전 기록) 소재 첫 낱말."""
    v = (t.get("대상") or "").strip()
    if not v:
        toks = [w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", t.get("소재") or "") if w not in {"올해", "지금", "우리"}]
        v = re.sub(r"(?<=..)(은|는|을|를|의)$", "", toks[0]) if toks else ""
    return v


def _target(t):
    return re.sub(r"\s+", "", _target_name(t)).lower()


def recent_brief(ch):
    """최근 추천(반복 금지용): 최근 4번의 소재 이름 + 최근 8번에서 2번 이상 나온 대상과 횟수.
    돌려줌: (프롬프트용 요약, 3번 이상 나와 이번엔 1개만 허용할 대상 집합)"""
    p = OUT / "history.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []
    rows = [r for r in rows if r.get("channel") == ch][-RECENT_RUNS:]
    names = sorted({t["소재"] for r in rows[-4:] for t in r.get("topics", []) if t.get("소재")})
    cnt, disp = {}, {}
    for r in rows:
        for t in r.get("topics", []):
            if _target(t):
                disp.setdefault(_target(t), _target_name(t))
        for k in {_target(t) for t in r.get("topics", [])} - {""}:
            cnt[k] = cnt.get(k, 0) + 1
    often = sorted(((disp[k], n) for k, n in cnt.items() if n >= 2), key=lambda x: -x[1])
    brief = {"살펴본_추천_횟수": len(rows), "자주_나온_대상": [{"대상": d, "나온_횟수": n} for d, n in often], "최근_추천_소재": names}
    return brief, {k for k, n in cnt.items() if n >= OFTEN_MAX}


# ---------------------------------------------------------------- 재료: 뉴스 · 검색어

def _news_feed(src, kw, lang):
    q = urllib.parse.quote(kw)
    if src == "bing":
        url = f"https://www.bing.com/news/search?format=rss&q={q}"                               # 관련도순(최신순은 엉뚱한 글이 섞임)
    else:
        q = urllib.parse.quote(f"{kw} when:{FRESH_DAYS}d")                                      # 관련도순 + 최근 14일
        url = f"https://news.google.com/rss/search?q={q}&" + ("hl=ko&gl=KR&ceid=KR:ko" if lang == "ko" else "hl=en-US&gl=US&ceid=US:en")
    rows = []
    for item in re.findall(r"<item>(.*?)</item>", fetch(url), re.S):
        title, link = _tag(item, "title"), _tag(item, "link")
        press = _tag(item, "News:Source") or _tag(item, "source")
        if press and title.endswith(" - " + press):
            title = title[: -len(press) - 3].strip()
        desc = "" if src == "google" else re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", _tag(item, "description"))).strip()  # 구글 요약은 제목 되풀이
        try:
            when = parsedate_to_datetime(_tag(item, "pubDate"))
        except Exception:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        real = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("url", [link])[0]
        if title and real:
            rows.append({"src": src, "when": when, "title": title, "desc": desc, "url": real, "press": press})
    return rows


def _relevant(kw, r, lang):
    """검색어와 상관있는 기사만: 블로그·광고성 글 빼고, 검색어 낱말이 제목·요약에 하나는 있어야 한다."""
    host = urllib.parse.urlparse(r["url"]).netloc.lower()
    if any(host == h or host.endswith("." + h) for h in NEWS_BLOCK_HOSTS) or NEWS_SPAM.search(r["title"]):
        return False
    if lang == "ko" and not HANGUL.search(r["title"]):
        return False
    text = (r["title"] + " " + r["desc"]).lower()
    return any(w.lower() in text for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", kw))


def news(keywords, per=5, cap=100, sources=("google", "bing"), lang="ko"):
    """최신 뉴스 — 구글(관련도순·최근 14일)과 빙(관련도순)을 번갈아 합쳐 키워드마다 per 개, 최근 30일만, 최신순으로 최대 cap 개.
    (둘 다 WebSearch 한도와 무관한 RSS. 2026-09-27: 최신순으로만 뽑으면 엉뚱한 글이 섞여서 관련도순 + 기간 제한으로 바꿈)"""
    cut = datetime.now(timezone.utc) - timedelta(days=NEWS_DAYS)
    jobs = [(src, kw) for kw in keywords for src in sources]

    def run(job):
        try:
            return job, _news_feed(job[0], job[1], lang)
        except Exception as e:
            log("뉴스 실패", job[0], job[1], str(e)[:80])
            return job, []

    with ThreadPoolExecutor(6) as ex:
        got = dict(ex.map(run, jobs))
    out, seen = [], set()
    for kw in keywords:
        lists = [[r for r in got.get((src, kw), []) if r["when"] >= cut and _relevant(kw, r, lang)] for src in sources]
        merged = [l[i] for i in range(max(map(len, lists), default=0)) for l in lists if i < len(l)]
        n = 0
        for r in merged:
            key = re.sub(r"\W", "", r["title"])[:40]
            if key in seen:
                continue
            seen.add(key)
            item = {"검색어": kw, "날짜": r["when"].astimezone(KST).strftime("%Y-%m-%d"), "제목": r["title"], "언론": r["press"], "url": r["url"]}
            if r["desc"] and r["desc"][:20] != r["title"][:20]:
                item["요약"] = r["desc"][:90]
            out.append(item)
            n += 1
            if n >= per:
                break
    out.sort(key=lambda r: r["날짜"], reverse=True)
    return out[:cap]


def trends(geo="KR", n=20):
    """구글 트렌드 일간 급상승 검색어 — 오늘 사람들이 무엇을 찾는지(검색어·검색량·관련 기사 2개)."""
    try:
        x = fetch(f"https://trends.google.com/trending/rss?geo={geo}")
    except Exception as e:
        log("트렌드 실패", str(e)[:80])
        return []
    out = []
    for item in re.findall(r"<item>(.*?)</item>", x, re.S)[:n]:
        try:
            d = parsedate_to_datetime(_tag(item, "pubDate")).astimezone(KST).strftime("%Y-%m-%d")
        except Exception:
            d = datetime.now(KST).strftime("%Y-%m-%d")
        arts = [{"제목": _tag(ni, "ht:news_item_title"), "언론": _tag(ni, "ht:news_item_source"), "url": _tag(ni, "ht:news_item_url")}
                for ni in re.findall(r"<ht:news_item>(.*?)</ht:news_item>", item, re.S)[:2]]
        out.append({"검색어": _tag(item, "title"), "검색량": _tag(item, "ht:approx_traffic"), "날짜": d, "기사": arts})
    return out


# ---------------------------------------------------------------- 추천 정확도 보정(2026-09-26 사용자 요청)
# 우리 채널에 올린 영상을 같은 기준(조회수는 안 보여 주고 제목만)으로 AI가 채점 → 올린 뒤 3일 조회수와 비교해
# 어떤 기준이 실제 조회수와 잘 맞는지 재고, 가중치를 조금씩 옮긴다. 근거(proof)는 '그때 유행'이라 나중에 못 재서 고정.
FIT_KEYS = ("korea", "paradox", "visual")


def views_3d(vid, published):
    """올린 뒤 3일째 조회수(대시보드 일별 기록). 기록 시작(09-15) 전에 올린 영상·3일 안 된 영상은 None."""
    vv = (VIEWS or {}).get(vid) or {}
    try:
        pub = datetime.fromisoformat(published.replace("Z", "+00:00")).astimezone(KST)
    except Exception:
        return None
    if datetime.now(KST) - pub < timedelta(days=3.5) or not vv:
        return None
    day = (pub + timedelta(days=3)).strftime("%Y-%m-%d")
    if min(vv) > pub.strftime("%Y-%m-%d"):
        return None
    later = sorted(d for d in vv if d >= day)
    return vv[later[0]] if later else None


def score_published(c, scored):
    """아직 채점 안 한 우리 영상을 제목만 보고 채점(채널당 한 번에 최대 40편). 조회수는 절대 보여 주지 않는다."""
    v = VIDEOS or {}
    todo = [(vid, r["title"]) for vid, r in v.items() if r.get("ch") == c["name"] and r.get("title") and vid not in scored][:40]
    if not todo:
        return 0
    sc = {k: c["scores"][k] for k in FIT_KEYS}
    prompt = (f"유튜브 채널 「{c['name']}」에 올린 영상 제목들이다. 조회수는 모른다고 치고, 제목과 소재만 보고 아래 기준으로 0~5 정수 채점하라.\n"
              + "\n".join(f"- {k}: {t}" for k, t in sc.items())
              + "\n[채널 공식]\n" + "\n".join(f"- {x}" for x in c["formula"][:3])
              + "\n도구를 쓰지 말고 JSON 하나만: {\"scores\": [{\"id\": \"영상 id\", \"korea\": 0, \"paradox\": 0, \"visual\": 0}]}\n"
              + json.dumps([{"id": vid, "제목": t} for vid, t in todo], ensure_ascii=False))
    got = _json(ask_claude(prompt, CFG.get("model", "sonnet"))[0])
    n = 0
    for r in got.get("scores", []):
        if r.get("id") in v:
            scored[r["id"]] = {"ch": c["name"], "title": v[r["id"]]["title"], "at": datetime.now(KST).strftime("%Y-%m-%d"),
                               "scores": {k: max(0, min(5, int(r.get(k, 0) or 0))) for k in FIT_KEYS}}
            n += 1
    return n


def _corr(a, b):
    n = len(a)
    if n < 3: return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0: return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (va * vb) ** 0.5


def _toks(s):
    stop = {"어떻게", "이유", "했을까", "까지", "그리고", "지금", "우리", "shorts", "하는", "있는", "없는", "무엇", "누가", "정말"}
    return {w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", s or "") if w not in stop}


def calibrate(c, scored):
    """실제 3일 조회수와 가장 잘 맞는 기준 쪽으로 가중치를 옮긴다. 데이터가 적을수록 원래 기준을 더 믿는다."""
    base = dict(c["weights"]); v = VIDEOS or {}
    rows = []
    for vid, s in scored.items():
        if s.get("ch") != c["name"] or vid not in v: continue
        y = views_3d(vid, v[vid].get("published", ""))
        if y is None: continue
        try:
            t = datetime.fromisoformat(v[vid]["published"].replace("Z", "+00:00")).timestamp() / 86400
        except Exception:
            continue
        rows.append((s["scores"], math.log10(y + 1), vid, t))
    # 채널이 크는 추세(초기 영상은 뭘 해도 적게 나옴)를 빼고 비교: 조회수(log)를 올린 날짜로 직선 맞춘 뒤 남는 차이만 본다
    if len(rows) >= 3:
        ts, ys = [r[3] for r in rows], [r[1] for r in rows]
        mt, my = sum(ts) / len(ts), sum(ys) / len(ys)
        vt = sum((x - mt) ** 2 for x in ts)
        slope = sum((x - mt) * (y - my) for x, y in zip(ts, ys)) / vt if vt else 0.0
        rows = [(r[0], r[1] - (my + slope * (r[3] - mt)), r[2], r[3]) for r in rows]
    corr = {k: round(_corr([r[0][k] for r in rows], [r[1] for r in rows]), 2) for k in FIT_KEYS}
    # 부드럽게: 가중치 × (1 + α·상관). 상관이 약하면 거의 안 움직이고, 자료가 쌓일수록(α↑) 더 믿는다.
    # 사용자 기준(한국 인지도×3 등)을 소수 영상으로 뒤집지 않게 α 는 최대 0.6, 결과는 0.5~4.5 로 묶는다.
    w = dict(base); alpha = 0.0
    if len(rows) >= 6:
        alpha = min(0.6, len(rows) / (len(rows) + 20))
        for k in FIT_KEYS:
            w[k] = round(min(4.5, max(0.5, base[k] * (1 + alpha * corr[k]))), 2)
    # 추천 → 실제: 추천했던 소재와 제목이 겹치는, 추천 뒤에 올린 영상
    hits, hp = [], OUT / "history.jsonl"
    recs = [json.loads(l) for l in hp.read_text(encoding="utf-8").splitlines() if l.strip()] if hp.exists() else []
    for vid, r in v.items():
        if r.get("ch") != c["name"]: continue
        vt = _toks(r.get("title"))
        best = None
        for run in recs:
            if run.get("channel") != c["name"] or (r.get("published") or "") < run["at"].replace(" ", "T"): continue
            for t in run.get("topics", []):
                tt = _toks((t.get("소재") or "") + " " + (t.get("제목") or ""))
                shared = vt & tt
                if len(shared) >= 2 and len(shared) / max(1, min(len(vt), len(tt))) >= 0.34 and (not best or len(shared) > best[0]):
                    best = (len(shared), run["at"], t)
        if best:
            hits.append({"추천시각": best[1], "소재": best[2].get("소재"), "추천점수": best[2].get("총점"), "영상": r.get("title"),
                         "url": f"https://www.youtube.com/shorts/{vid}" if r.get("short") else f"https://www.youtube.com/watch?v={vid}",
                         "3일조회": views_3d(vid, r.get("published", "")), "지금조회": r.get("views")})
    return {"weights": w, "base": base, "n": len(rows), "corr": corr, "alpha": round(alpha, 2), "hits": hits,
            "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M")}


# ---------------------------------------------------------------- 판단

def gather(c, ob, cal, trend):
    """채널 하나의 판단 재료(표 줄 + R번호). 돌려줌: (프롬프트 재료, 근거로 쓸 수 있는 주소, 주소→기사 날짜, 1개만 허용할 대상, 요약 숫자, R번호→주소)"""
    en = c.get("lang") == "en"
    R = Refs()
    recent, overused = recent_brief(c["name"])
    ours, done = ours_brief(c["name"]), done_topics(c)
    kr_news = news(c["news"], per=c.get("news_per", 5))
    en_news, eo = [], None
    if en:
        eo = en_outliers(EN_CONF)
        en_news = news(c.get("news_en", []), per=4, cap=40, sources=("google",), lang="en")
        mats = [("영어권에서 지금 빨리 크는 한국 영상(유튜브 RSS — 그 채널 평소 대비 배수·하루 조회수) · 공급 · 주제별 수요", sec_en(eo, R))]
    else:
        mats = [("지금 한국 유튜브에서 평소보다 몇 배 빨리 크는 영상(발굴)", sec_outliers(ob, R))]
    mats += [("우리 채널 성적", sec_ours(ours, R)), ("이미 만든 편", sec_done(done)), ("최근 추천(반복 금지용)", sec_recent(recent)),
             (f"최신 한국 뉴스(최근 {NEWS_DAYS}일)", sec_news(kr_news, R))]
    if en:
        mats.append((f"영어권 언론이 지금 다루는 한국(최근 {FRESH_DAYS}일)", sec_news(en_news, R)))
    mats.append(("지금 한국에서 검색이 급상승한 말(구글 트렌드) — 채널 공식에 맞을 때만 쓴다", sec_trend(trend, R)))
    allowed, dates = set(R.by_url), {}      # 재료로 실제 보낸 주소만 근거로 인정
    for r in kr_news + en_news:
        dates.setdefault(r["url"], r["날짜"])
    for t in trend:
        for a in t["기사"]:
            if a.get("url"):
                dates.setdefault(a["url"], t["날짜"])
    info = {"news_n": len(kr_news) + len(en_news), "fresh_news_n": sum(1 for r in kr_news + en_news if r["날짜"] >= fresh_cut()),
            "trend_n": len(trend), "outliers_at": eo["기준시각"] if en else ob.get("기준시각"),
            "outliers_n": len(eo["뜨는_영어권_한국영상"]) if en else len(ob.get("쇼츠", [])) + len(ob.get("본편", [])),
            "ours_n": ours["편수"], "done_n": len(done["편_폴더"]), "often": [x["대상"] for x in recent["자주_나온_대상"]]}
    return {"mats": mats, "recent": recent, "calib": cal}, allowed, dates, overused, info, R.by_id


def build_prompt(c, data):
    sc = c["scores"]; keys = list(sc); n = CFG["per_channel"]; ask = n + EXTRA
    n_fresh, detail = max(3, n // 3), CFG.get("detail_top", 8)
    cal = data.get("calib") or {}
    n_cal = cal.get("n", 0)
    cal_line = ", ".join(f"{k} {v:+.2f}" for k, v in (cal.get("corr") or {}).items()) if n_cal >= 6 else "아직 자료 부족(6편 미만) — 기준표 그대로"
    rec = data["recent"]
    often = ", ".join(f"{x['대상']}({x['나온_횟수']}번)" for x in rec.get("자주_나온_대상", []))
    repeat_rule = (f"- 반복 금지(가장 중요): 최근 {rec.get('살펴본_추천_횟수', 0)}번의 추천에 자주 나온 대상 — {often}. 이 대상들은 각각 1개까지만, "
                   f"그것도 최근 {FRESH_DAYS}일 안의 새 기사나 지금 새로 터지는 영상이 근거일 때만 낸다. " if often else "- 반복 금지(가장 중요): ") + \
                  "공식에 예로 든 이름들은 '이만큼 유명한 대상'이라는 예시일 뿐이다 — 그 이름을 되풀이하지 말고 같은 급의 다른 대상을 찾아라."
    L = [f"너는 유튜브 채널 「{c['name']}」의 소재 기획자다. 아래 재료만 보고, 지금 만들면 조회수가 가장 크게 터질 소재 {ask}개를 골라라"
         f"(프로그램이 같은 대상 겹침을 걸러 {n}개를 쓴다).",
         "", "[채널 형식]", c["format"],
         "", "[떡상 공식 — 사용자 확정, 반드시 따른다]"] + [f"- {x}" for x in c["formula"]] + [
         "", "[점수 기준 — 각 0~5 정수]"] + [f"- {k}: {v}" for k, v in sc.items()] + [
         "", f"[우리 채널 실측 — 올린 영상 {n_cal}편의 3일 조회수와 기준의 상관(1에 가까울수록 조회수와 잘 맞음)]", cal_line,
         "", "[규칙]",
         "- 근거는 재료에 있는 번호(R…)만 쓴다. 지어내지 않는다. 근거가 약하면 proof 점수를 낮게 준다.",
         "- 이미 만든 편과 같은 소재는 빼라(다른 각도의 후속은 된다 — 후속 줄에 적기).",
         "- 최근 추천과 같은 소재는 새 근거가 있을 때만 다시 낸다.",
         repeat_rule,
         f"- 다양성: {ask}개는 서로 다른 소재, 같은 대상은 2개까지. 갈래를 섞어라 — ① 최근 {FRESH_DAYS}일 뉴스·검색어에서 나온 새 이슈(최소 {n_fresh}개) "
         "② 우리 대박 편의 새 후속 ③ 지금 빨리 크는 영상에서 나온 소재 ④ 아직 아무도 안 한 새 각도.",
         "- 최신 우선: 점수가 비슷하면 최근 기사에 근거한 소재를 앞에 둔다. 기사를 근거로 쓸 때는 메모에 기사 날짜를 적는다.",
         "- 확인 안 된 숫자는 제목에 쓰지 말고 확인 줄에 넣어라."]
    if c.get("output_note"):
        L.append("- " + c["output_note"])
    L += ["", "[출력 형식 — JSON·설명·머리말 없이 아래 줄 형식만. 소재마다 '## '로 시작, 총점이 높을 것 같은 순서]",
          "## 소재 한 줄 이름",
          "대상: 핵심 대상 하나(건물·기업·인물·장소·제도의 가장 널리 쓰는 이름)",
          f"점수: {' '.join(keys)} 순서로 0~5 정수 {len(keys)}개 (예: 5 3 2 4)",
          "제목: 유튜브 제목 초안(#shorts 빼고)",
          "왜: 왜 터질까 — 근거를 짚어 2문장 이내",
          "근거: R번호 = 무엇이 근거인가(기사면 날짜) | R번호 = …",
          "첫문장: 영상 첫 문장",
          "장면: 화면으로 무엇을 보여주나(1문장)",
          "확인: 제작 전 확인할 숫자·사실 | …(3개 이내)",
          "위험: 틀리거나 반려될 위험(1문장)",
          "후속: 우리 대박 편의 후속이면 그 편 이름(아니면 이 줄 생략)",
          f"위에서 {detail}개는 모든 줄을 쓰고, 그 뒤 소재는 대상·점수·제목·왜(1문장)·근거 줄만 쓴다."]
    for i, (label, text) in enumerate(data["mats"], 1):
        L += ["", f"[재료 {i} — {label}]", text]
    L += ["", f"오늘은 {datetime.now(KST).strftime('%Y-%m-%d')} 이다."]
    return "\n".join(L)


FIELD = {"대상": "대상", "제목": "제목", "첫문장": "첫문장", "왜": "왜_터질까", "왜_터질까": "왜_터질까",
         "장면": "보여줄_장면", "보여줄_장면": "보여줄_장면", "위험": "위험", "후속": "후속"}


def parse_answer(text, refs, keys):
    """줄 형식 답('## ' 블록) → {"topics": [...]}. 블록이 없으면 JSON 으로 읽는다(예전 형식·밖에서 받은 답). R번호는 주소로 되돌린다."""
    blocks = re.split(r"^\s*##\s+", text, flags=re.M)[1:]
    if not blocks:
        got = _json(text)
        for t in got.get("topics", []):
            for e in (t.get("근거") or []) if isinstance(t, dict) else []:
                if isinstance(e, dict):
                    e["url"] = refs.get(str(e.get("url", "")).strip(), e.get("url"))
        return got
    topics = []
    for b in blocks:
        lines = [l.strip() for l in b.strip().splitlines() if l.strip()]
        if not lines:
            continue
        t = {"소재": lines[0].strip("#* ").strip(), "후속": ""}
        for ln in lines[1:]:
            m = re.match(r"^[-*•\s]*\**([가-힣_A-Za-z]+)\**\s*[:：]\s*(.*)$", ln)
            if not m:
                continue
            k, v = m.group(1), m.group(2).strip()
            if k in FIELD:
                t[FIELD[k]] = "" if (k == "후속" and v in ("없음", "-", "해당 없음")) else v
            elif k == "점수":
                named = dict(re.findall(r"([a-z]+)\s*[=:]?\s*([0-5])", v))
                t["점수"] = {q: int(named.get(q, 0)) for q in keys} if named else dict(zip(keys, map(int, re.findall(r"[0-5]", v))))
            elif k == "근거":
                ev = []
                for part in v.split("|"):
                    mm = re.match(r"\s*\[?(R\d+)\]?\s*[=:：\-–—]?\s*(.*)", part)
                    if mm and mm.group(1) in refs:
                        ev.append({"url": refs[mm.group(1)], "메모": mm.group(2).strip()})
                t["근거"] = ev
            elif k in ("확인", "확인할_사실"):
                t["확인할_사실"] = [x.strip() for x in v.split("|") if x.strip()]
        topics.append(t)
    return {"topics": topics}


def _json(text):
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if not m:
        raise RuntimeError("답 형식 없음: " + text[:300])
    return json.loads(m.group(1))


SYSTEM = "너는 요청받은 형식 그대로만 답한다. 도구는 쓰지 않는다."
# 토큰 절약(2026-09-27): claude 기본 지시문 대신 SYSTEM, 도구·MCP(openchrome·higgsfield)·사용자 설정(플러그인·훅)·스킬 없이.
# --bare 는 구독(OAuth) 로그인을 못 써서 쓰지 않는다(API 키 전용).
LEAN = ["--system-prompt", SYSTEM, "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--setting-sources", "project", "--disable-slash-commands", "--no-session-persistence"]


def ask_claude(prompt, model):
    """claude -p(구독) 한 턴 → (답 글, 사용량). 빈 폴더에서 부른다(프로젝트 문서를 안 읽게)."""
    cmd = ["claude", "-p", "--output-format", "json", "--model", model, "--max-turns", "1"] + LEAN
    if CFG.get("effort"):
        cmd += ["--effort", CFG["effort"]]
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900, cwd=tmp)
    try:
        env = json.loads(r.stdout)
    except Exception:
        raise RuntimeError(f"claude 실패 {r.returncode}: {(r.stderr or r.stdout)[:300]}")
    if r.returncode != 0 or env.get("is_error"):
        raise RuntimeError(f"claude 실패 {r.returncode}: {str(env.get('result') or r.stderr)[:300]}")
    u = env.get("usage") or {}
    use = {"in": sum(u.get(k, 0) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
           "out": u.get("output_tokens", 0) or 0, "think": (u.get("output_tokens_details") or {}).get("thinking_tokens", 0) or 0,
           "usd": env.get("total_cost_usd")}
    return env.get("result") or "", use


def tok_str(use):
    if not use:
        return ""
    s = f"토큰 입력 {use['in']:,}·출력 {use['out']:,}" + (f"(생각 {use['think']:,})" if use.get("think") else "")
    return s + (f" ${use['usd']:.2f}" if use.get("usd") else "")


def clean(c, got, allowed, weights=None, dates=None, overused=()):
    """AI 답 정리: 점수→총점(보정 가중치), 지어낸 근거 주소 버림, 근거 기사 날짜로 '최신' 표시,
    같은 대상은 2개까지(최근 추천에 3번 이상 나온 대상은 1개) — 2026-09-27 '똑같은 주제만 나온다'."""
    w = weights or c["weights"]; top = 5 * sum(w.values())
    dates, cut = dates or {}, fresh_cut()
    out = []
    for t in (got.get("topics", []) if isinstance(got, dict) else []):
        if not isinstance(t, dict) or not t.get("소재"):
            continue
        raw = t.get("점수") if isinstance(t.get("점수"), dict) else {}
        s = {}
        for k in list(w) + [k for k in c["weights"] if k not in w]:
            try:
                s[k] = max(0, min(5, int(round(float(raw.get(k, 0) or 0)))))
            except (TypeError, ValueError):
                s[k] = 0
        t["점수"] = s
        t["총점"] = round(sum(s.get(k, 0) * w[k] for k in w) / top * 100)
        t["근거"] = [e for e in (t.get("근거") or []) if isinstance(e, dict) and e.get("url") in allowed]   # 지어낸 주소는 버린다
        ds = sorted((dates[e["url"]] for e in t["근거"] if e["url"] in dates), reverse=True)
        t.pop("최신", None)
        if ds and ds[0] >= cut:
            t["최신"] = ds[0]      # 최근 14일 기사·검색어에 근거(대시보드 📰)
        out.append(t)
    out.sort(key=lambda t: (-t["총점"], 0 if t.get("최신") else 1))
    kept, seen = [], {}
    for t in out:
        k = _target(t)
        if k and seen.get(k, 0) >= (1 if k in overused else 2):
            continue
        seen[k] = seen.get(k, 0) + 1
        kept.append(t)
    return kept[:CFG["per_channel"]]


def main():
    args = sys.argv
    opt = lambda k: args[args.index(k) + 1] if k in args and args.index(k) + 1 < len(args) else None
    only, dry, answers, label = opt("--channel"), "--dry" in args, opt("--answers"), opt("--label") or "외부 답"
    OUT.mkdir(exist_ok=True)
    if "--done-only" in args:
        for c in CFG["channels"]:
            log(c["name"], "만든 편", len(scan_done(c)))
        return
    subprocess.run(["git", "fetch", "-q", "origin", "gh-pages"], cwd=ROOT)
    latest_p = OUT / "latest.json"
    latest = json.loads(latest_p.read_text(encoding="utf-8")) if latest_p.exists() else {"channels": {}}
    global VIDEOS, VIEWS
    VIDEOS, VIEWS = gh_json("videos.json") or {}, gh_json("video_views.json") or {}
    ob = outliers_brief()
    trend = [] if (answers or "--score-only" in args) else trends()
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    sp = OUT / "scored.json"; scored = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    cp = OUT / "calibration.json"; calib_all = json.loads(cp.read_text(encoding="utf-8")) if cp.exists() else {}
    for c in CFG["channels"]:
        name = c["name"]
        if only and name != only: continue
        if not dry and not answers:
            try:
                k = score_published(c, scored)
                if k: sp.write_text(json.dumps(scored, ensure_ascii=False, indent=1), encoding="utf-8"); log(name, "우리 영상 채점", k, "편")
            except Exception as e:
                log(name, "우리 영상 채점 실패(보정은 지난 값):", str(e)[:200])
        cal = calib_all[name] = calibrate(c, scored)
        view = {k: cal[k] for k in ("weights", "base", "n", "corr", "alpha", "hits", "updated")}
        log(name, f"보정: {cal['n']}편, 상관 {cal['corr']}, 가중치 {cal['weights']}, 추천→실제 {len(cal['hits'])}편")
        if "--score-only" in args:   # 우리 영상 채점·보정만(추천은 안 함)
            if name in latest["channels"]: latest["channels"][name]["calib"] = view
            continue
        mp = OUT / f"_materials_{name}.json"
        try:
            at = now
            if answers:   # --dry 로 모아 둔 재료 + 밖에서 받은 답
                m = json.loads(mp.read_text(encoding="utf-8"))
                allowed, dates, overused, info, at = set(m["allowed"]), m["dates"], set(m["overused"]), m["info"], m.get("at", now)
                ap = Path(answers) / f"{name}.txt"
                ap = ap if ap.exists() else Path(answers) / f"{name}.json"
                got, use, model = parse_answer(ap.read_text(encoding="utf-8"), m.get("refs", {}), list(c["scores"])), None, label
            else:
                data, allowed, dates, overused, info, refs = gather(c, ob, cal, trend)
                prompt = build_prompt(c, data)
                info["prompt_chars"] = len(prompt)
                log(name, f"재료: {'영어권 한국영상' if c.get('lang') == 'en' else '발굴'} {info['outliers_n']}, 우리 {info['ours_n']}편, "
                          f"만든 편 {info['done_n']}, 뉴스 {info['news_n']}(최근 {FRESH_DAYS}일 {info['fresh_news_n']}), 트렌드 {info['trend_n']}, "
                          f"자주 나온 대상 {info['often'] or '없음'}, 프롬프트 {len(prompt):,}자")
                if dry:
                    (OUT / f"_prompt_{name}.txt").write_text(prompt, encoding="utf-8")
                    mp.write_text(json.dumps({"at": now, "allowed": sorted(allowed), "dates": dates, "overused": sorted(overused), "info": info,
                                              "refs": refs}, ensure_ascii=False), encoding="utf-8")
                    continue
                model = CFG.get("model", "sonnet")
                text, use = ask_claude(prompt, model)
                got = parse_answer(text, refs, list(c["scores"]))
            topics = clean(c, got, allowed, cal["weights"], dates, overused)
            fresh_n = sum(1 for t in topics if t.get("최신"))
            latest["channels"][name] = {"at": at, "model": model, "outliers_at": info.get("outliers_at"), "news_n": info.get("news_n"),
                                        "trend_n": info.get("trend_n"), "fresh_n": fresh_n, "prompt_chars": info.get("prompt_chars"),
                                        "tokens": use, "topics": topics, "calib": view}
            with (OUT / "history.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": at, "channel": name, "topics": [{"소재": t.get("소재"), "대상": t.get("대상"), "제목": t.get("제목"),
                                                                            "총점": t["총점"], "최신": t.get("최신")} for t in topics]}, ensure_ascii=False) + "\n")
            log(name, "추천", len(topics), "개", tok_str(use), f"· 📰최신 {fresh_n}개 ·",
                " / ".join(f"{t.get('소재')} {t['총점']}" for t in topics[:6]), "…")
        except Exception as e:
            log(name, "실패 — 지난 추천 유지:", str(e)[:300])
            if name in latest["channels"]:
                latest["channels"][name]["stale"] = f"{now} 갱신 실패"
    if not dry:
        cp.write_text(json.dumps(calib_all, ensure_ascii=False, indent=1), encoding="utf-8")
        latest["at"] = now
        latest_p.write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
