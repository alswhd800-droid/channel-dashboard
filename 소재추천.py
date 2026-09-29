#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""소재 추천기 — 하루 2번(한국시간 07·15시, 맥 launchd) '조회수 터질 만한 소재'를 AI가 판단해 대시보드 🎯 소재 탭에 올린다.

2026-09-26 사용자: "대시보드 시장조사를 하루 2번씩 조회수 빵빵 터질 만한 소재를 판단해서 가져오게" → 거대한비밀·거인의무덤, 내 맥, 07·15시.
2026-09-27 사용자: "새 영어채널도, 5개 말고 20개씩, 너무 똑같은 주제만 나오고 최신 이슈 반영이 안 된다"
  → 영어채널 The Paradox Desk 추가 · 채널당 20개 · 뉴스 빙+구글(최근 14일) · 구글 트렌드 · 영어권 한국 영상(유튜브 RSS)
    · 최근 추천에 자주 나온 대상 억제 + 같은 대상 2개까지 · 근거 기사 날짜로 📰 최신 표시.
2026-09-27 사용자: "논스킵은 '당신이 몰랐던 이야기'처럼 신창원·개구리소년 같은 미스터리·사건 이야기 채널"
  → 논스킵 추가 · 같은 장르 채널 훑기를 채널 설정("genre")으로 일반화 · 발굴 재료를 채널 키워드("outlier_keywords")로 줄임
    · 채널별 점수 이름("labels")을 대시보드에 표시.
2026-09-28 사용자: "논스킵채널에.. 이런소재도 좋지만 .기묘한밤처럼.. 심야 괴담 미스테리. .소재도 추가해서.. 완벽하게 믹스하고싶은데"
  → 채널 설정 "kinds"(갈래) — 논스킵 사건·괴담: 갈래마다 공식·최소 개수(20개 중 8개씩), 답에 '갈래:' 줄, 뒤처리 keep_kinds
    · 장르 파일 채널에 "kind"(괴담 채널 8곳 추가) — 뜨는 영상·공급도 갈래마다 자리를 남긴다 · 대시보드 갈래 딱지·[전체·사건·괴담] 칩.
2026-09-29 사용자: "자극적이고 조회수 빵빵 터질 만한 소재로 찾아야 하는데 소재가 다 별로야, 점수는 높다는데 다시 손봐야 할 듯"
  → 점수 다시 짬: AI가 '기사가 있다'로 채우던 근거(proof)를 빼고 ① hook(자극·클릭 충동, AI) ② demand(시장 수요 — 프로그램이 유튜브 검색
    조회수로 잼, AI 안 씀)를 가장 크게. hook 은 우리 채널(또는 같은 장르) 실제 상위·하위 5편을 기준점으로 상대 채점(5점 최대 3개·평균 3 이하).
    · 뉴스 최소 개수·'최신 우선' 규칙을 없애고 뉴스는 타이밍 가산 재료로만 · 채널마다 금지 유형(ban·ban_words)
    · 최근 7일 안에 만든 편의 대상·후속은 빼고, 더 오래된 만든 편과 같은 대상은 hook 4↑·demand 3↑일 때만 · 후보 30개 → 수요 측정 → 총점순 20개.

입력(판단 재료 — 전부 프로그램이 모은다, AI 토큰 0):
  · 발굴 결과(한국어 채널): gh-pages 의 data/outliers.json (발굴.py 가 06·14·21시에 찾은 '채널 평소보다 몇 배 빨리 크는 영상')
    — 채널 키워드가 있으면 종합 상위 8편 + 키워드 든 영상만
  · 같은 장르 채널(영어채널·논스킵): 채널 설정 "genre" 의 파일(소재추천_영어재료.json·소재추천_장르_논스킵.json)의 채널을
    유튜브 RSS(할당량 0)로 훑어 평소 대비 배수·하루 조회수 + 최근 공급. RSS 가 막히면 3일 안의 지난 성공분(topics/_rss_cache.json)
  · 우리 채널 성적: gh-pages 의 data/videos.json (무엇이 터졌고 무엇이 멈췄나)
  · 이미 만든 편: 각 채널 episodes 폴더 이름 (반복 금지). 폴더를 못 보는 예약 실행은 topics/done.json 사본
  · 최근 추천: topics/history.jsonl — 최근 추천 소재 + 자주 나온 대상(최근 8번 중 몇 번)
  · 최신 뉴스: 빙 뉴스(최신순) + 구글 뉴스(최근 14일) RSS 를 합쳐 키워드마다 가장 최근 기사, 최근 30일만 (키워드는 소재추천_기준.json)
  · 지금 뜨는 검색어: 구글 트렌드 한국 일간 급상승(검색어 + 관련 기사)
  · 채널 공식·점수 기준: 소재추천_기준.json (사용자 확정 기준을 그대로 옮김, 바뀌면 이 파일만 고친다)
  · 자극 기준점: 우리 채널 실제 성적 상위·하위 5편(같은 형식 평소 대비 배수) — 올린 지 3일 넘은 영상이 5편 미만이면 같은 장르(또는 발굴) 영상
판단: `claude -p`(구독 안에서) — 채널마다 1번, 후보 30개(설정 "candidates")와 소재마다 유튜브 검색어 1~2개.
수요 실측(프로그램, AI 토큰 0): 검색어마다 유튜브 검색 상위 15개(결과 페이지, 막히면 yt-dlp) → 최대 조회수·상위 3개 중앙값·10만+ 편수 → 0~5.
  같은 검색어 24시간 캐시(topics/_demand_cache.json), 동시 6개. 검색이 실패한 소재는 '측정 못 함'(총점에서 그 항목을 빼고 계산).
토큰 절약(2026-09-27 사용자: "성능은 유지하면서 토큰을 최대한 적게"):
  · claude 기본 지시문·도구·MCP(openchrome·higgsfield)·플러그인·스킬을 빼고 짧은 지시문 하나로 부른다(LEAN — 호출마다 붙던 군더더기).
  · 재료는 JSON 대신 표 줄로, 긴 주소는 R번호로 보낸다(답의 R번호는 프로그램이 주소로 되돌린다).
  · 답도 JSON 대신 줄 형식. 위에서 detail_top 개만 제작 메모(첫문장·장면·확인·위험)까지, 나머지는 제목·이유·근거만.
  · 토큰 사용량을 로그와 latest.json(tokens)에 남긴다.
뒤처리(프로그램): 지어낸 근거 주소 버림 · hook 부풀림 깎기 · 금지 말(ban_words) 든 소재 빼기 · 이미 만든 편 거르기
  · 같은 대상 2개까지(최근 3번 이상 나온 대상은 1개) · 근거 기사 날짜로 '최신' 표시(점수가 같을 때만 앞에)
  · 갈래가 있는 채널은 갈래마다 최소 개수 자리를 남기고 나머지는 총점순.
출력: topics/latest.json (대시보드), topics/history.jsonl (나중에 추천 vs 실제 조회수 맞춰 보기)

쓰기:
  python3 소재추천.py                    # 모든 채널
  python3 소재추천.py --channel 거대한비밀
  python3 소재추천.py --dry              # 재료만 모아 topics/_prompt_채널.txt · _materials_채널.json 저장(AI 안 부름)
  python3 소재추천.py --answers 폴더 [--label 이름]
                                        # claude 를 못 쓸 때(구독 한도 등): --dry 재료 + 폴더/채널.txt(같은 줄 형식 답, 또는 .json)로 마무리
                                        # 보통 실행도 재료와 AI 답(topics/_answers/채널.txt)을 남긴다 → `--answers topics/_answers --label sonnet`
                                        # 로 AI 없이 수요 측정·거르기·총점만 다시 할 수 있다(기준 파일을 고친 뒤 확인할 때)
  python3 소재추천.py --score-only       # 우리 영상 채점·정확도 보정만
  python3 소재추천.py --done-only        # 편 폴더를 읽어 topics/done.json 만 갱신(데스크톱에서 — 비용_자동갱신.sh 가 편마다 부름)
  python3 소재추천.py --pick 거대한비밀 3 5    # 대시보드 3·5위를 '만들기로 함'에 올리고 바로 대시보드에 올림(이름 일부도 됨)
  python3 소재추천.py --link P3 --folder 030-한옥기둥 --video 영상ID   # 자동으로 못 맞춘 편 폴더·영상을 직접 연결
  python3 소재추천.py --unpick P3 · --picks    # 목록에서 빼기 · 목록 보기   (--no-push: 올리지 않음)
"""
import html
import json
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
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
_GENRE = {}   # 장르 파일(같은 장르 채널 목록) 캐시 — 채널 설정의 "genre": {"file": …}


def genre_conf(name):
    if name not in _GENRE:
        p = ROOT / name
        _GENRE[name] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _GENRE[name]
VIDEOS, VIEWS = None, None   # gh-pages 의 우리 영상 목록·일별 조회수(main 에서 한 번 읽음)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
NEWS_DAYS = 30     # 이보다 오래된 기사는 재료에서 뺀다
FRESH_DAYS = 14    # 이 안의 기사·검색어에 근거하면 '최신' 소재(📰)
RECENT_RUNS = 8    # 자주 나온 대상을 셀 때 보는 최근 추천 횟수(하루 2번 → 4일)
OFTEN_MAX = 3      # 최근 추천에서 이만큼 이상 나온 대상은 이번에 1개까지만
EXTRA = 2          # 대상 제한으로 빠질 몫까지 몇 개 더 받는다(설정 "candidates" 가 없을 때)
MADE_DAYS = 7      # 이 안에 만든 편의 대상·후속은 추천에서 뺀다(2026-09-28 어제 만든 편의 후속이 목록 위를 채움)
RSS_CACHE = OUT / "_rss_cache.json"
# 점수 이름 기본값(채널 설정 "labels" 가 덮는다) — 대시보드는 latest.json 의 labels 순서대로 막대를 그린다
DEFAULT_LABELS = {"hook": "자극", "demand": "수요", "korea": "한국 인지도", "paradox": "역설", "visual": "화면", "proof": "근거"}
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


def sec_genre(eo, R):
    kd = any(r.get("갈래") for r in eo["hot"] + eo["supply"])   # 갈래가 있는 장르(논스킵 사건·괴담)는 채널 갈래 칸을 더한다
    g = lambda r: f"{r.get('갈래', '')}|" if kd else ""
    L = [f"기준 {eo['at']} · 훑은 채널 {eo['scanned']} · 칸: 번호|{'갈래|' if kd else ''}종류|평소대비(배)|하루조회|경과일|채널|제목"]
    L += [f"{R(r['url'])}|{g(r)}{r['종류']}|{r['평소대비']}|{r['하루조회']}|{r['경과일']}|{r['채널']}|{r['제목']}" for r in eo["hot"]] or ["(없음)"]
    L.append(f"최근 60일 같은 장르 본편(공급 — 같은 소재·각도가 이미 있나) · 칸: 번호|{'갈래|' if kd else ''}경과일|조회|채널|제목")
    L += [f"{R(r.get('url'))}|{g(r)}{r['경과일']}|{r['조회']}|{r['채널']}|{r['제목']}" for r in eo["supply"]]
    if eo.get("table"):
        L.append("주제별 수요·공급(조사표) · 칸: 주제|최근12개월 편수|그중 10만+|100만+|최근24개월 최고")
        L += [f"{r['주제']}|{r['최근12개월_편수']}|{r['그중_10만이상']}|{r['최근12개월_100만이상']}|{r['최근24개월_최고']}" for r in eo["table"]]
    return "\n".join(L)


def sec_ours(o, R):
    if not o["편수"]:
        return "아직 올린 영상 없음"
    row = lambda r: f"{R(r['url'])}|{r['조회']}|{'쇼츠' if r['쇼츠'] else '본편'}|{r['경과일']}|{r['제목']}"
    return "\n".join([f"올린 영상 {o['편수']}편 · 칸: 번호|조회|종류|경과일|제목", "잘된 영상:"] + [row(r) for r in o["잘된_영상"]]
                     + ["안된 영상:"] + [row(r) for r in o["안된_영상"]])


def sec_done(d):
    t = [re.sub(r"\s+", " ", re.sub(r"#\S+", "", x)).strip()[:45] for x in d["올린_영상_제목"]]
    rec = d.get("최근")
    return ((f"최근 {MADE_DAYS}일 안에 만든 편(이 대상·후속은 내지 마라): " + " / ".join(rec) + "\n") if rec else "") + \
        "편 폴더: " + (" / ".join(d["편_폴더"]) or "없음") + "\n올린 영상 제목: " + (" / ".join(t) or "없음")


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


def genre_outliers(conf, flt=None, days=30, top=25):
    """같은 장르 채널을 RSS 로 훑는다(할당량 0). 발굴.py 와 같은 생각: 절대 조회수가 아니라
    그 채널 평소(최근 영상 중간값, 쇼츠·본편 따로) 대비 배수 + 속도(하루 조회수). 최근 60일 본편은 '공급'으로 따로 준다.
    flt: 제목 거르기(영어채널은 한국 관련만). 2026-09-27 영어채널 전용에서 일반화(논스킵 미스터리 채널 추가)."""
    now = datetime.now(timezone.utc)

    def run(ch):
        try:
            return ch, _yt_feed(ch["id"])
        except Exception:
            return ch, None

    chans = conf.get("rss_channels", [])
    kinds = list(dict.fromkeys(ch["kind"] for ch in chans if ch.get("kind"))) if conf.get("kind_min") else []
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
    cand, supply, pool = [], [], []
    for ch, name, rows, seen_at in feeds:
        for r in rows:
            r["age_d"] = max((seen_at - r["pub"]).total_seconds() / 86400, 0.25)
        for r in rows:
            if flt and not flt.search(r["title"]):
                continue
            same = [x["views"] for x in rows if x["short"] == r["short"] and x["id"] != r["id"] and x["age_d"] >= 3]
            base = statistics.median(same) if len(same) >= 3 else None
            row = {"제목": r["title"], "채널": name or ch.get("name"), "종류": "쇼츠" if r["short"] else "본편", "조회": r["views"],
                   "평소대비": round(r["views"] / max(base, 1), 1) if base else None, "하루조회": round(r["views"] / r["age_d"]),
                   "경과일": round(r["age_d"], 1), "url": r["url"]}
            if kinds:
                row["갈래"] = ch.get("kind") or kinds[0]
            if not r["short"] and r["age_d"] <= 60:
                supply.append({"제목": r["title"], "채널": row["채널"], "경과일": round(r["age_d"]), "조회": r["views"], "url": r["url"],
                               **({"갈래": row["갈래"]} if kinds else {})})
                pool.append({k: row.get(k) for k in ("제목", "채널", "조회", "평소대비", "경과일", "갈래")})   # 자극 기준점 후보(anchors)
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
    # 갈래(논스킵 사건·괴담)가 있으면 뜨는 영상은 갈래마다 kind_min 자리, 공급은 갈래마다 같은 몫 — 매일 올리는 채널 한 갈래가 다 차지하지 않게
    hot = keep_kinds(cand, top, {k: conf["kind_min"] for k in kinds}) if kinds else cand[:top]
    supply = keep_kinds(supply, 40, {k: 40 // len(kinds) for k in kinds}) if kinds else supply[:40]
    return {"at": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "scanned": f"{live}/{len(chans)}" + (f" (+지난 성공분 {old})" if old else ""),
            "hot": hot, "supply": supply, "pool": pool, "table": conf.get("supply", [])}


def keep_kinds(rows, n, mins, key="갈래"):
    """순서대로 놓인 rows 에서 n 개를 고르되 갈래마다 최소 mins[갈래] 개 자리를 남긴다(모자라면 있는 만큼). 순서는 그대로.
    2026-09-28 논스킵 사건·괴담 믹스 — 점수로만 자르면 한 갈래가 통째로 밀려난다."""
    must = set()
    for k, m in mins.items():
        must.update(id(r) for r in [r for r in rows if r.get(key) == k][:m])
    free, out = n - len(must), []
    for r in rows:
        if id(r) in must:
            out.append(r)
        elif free > 0:
            out.append(r)
            free -= 1
    return out


def filter_outliers(ob, c, keep=8, cap=24):
    """발굴 결과를 채널에 맞게 줄인다(토큰 절약): 종합 상위 keep 개 + 채널 키워드가 제목에 든 영상(최대 cap).
    키워드가 없는 채널은 그대로. 2026-09-27 — 발굴 40편 중 대부분이 예능·스포츠라 채널과 무관했다."""
    kw = c.get("outlier_keywords")
    if not kw:
        return ob
    rx = re.compile(kw, re.I)
    out = dict(ob)
    for k in ("쇼츠", "본편"):
        rows = ob.get(k, [])
        out[k] = [r for i, r in enumerate(rows) if i < keep or rx.search(r.get("제목") or "")][:cap]
    out["뜨는채널"] = [r for i, r in enumerate(ob.get("뜨는채널", [])) if i < 4 or rx.search(r.get("채널") or "")][:10]
    return out


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


def anchors(c, eo=None, fob=None, k=5):
    """hook(자극) 기준점 — 실제 성적 상위 k편(5점급)·하위 k편(1점급). 기준 없는 AI 자기 채점이 3~5에 몰리던 것을 막는다(2026-09-29).
    우리 채널: 같은 형식(쇼츠·본편) 평소(중앙값) 대비 배수로 줄 세운다 — 상위는 올린 지 1일 넘은 영상, 하위는 3일 넘은 영상에서.
    올린 지 3일 넘은 우리 영상이 5편 미만이면(새 채널) 같은 장르 채널의 최근 60일 본편(평소 대비 배수), 그것도 없으면 발굴 영상으로 대신한다."""
    now = datetime.now(timezone.utc)
    clean_t = lambda s: re.sub(r"\s+", " ", re.sub(r"#\S+", "", str(s or ""))).strip()
    rows = []
    for r in (VIDEOS or {}).values():
        if r.get("ch") != c["name"] or not r.get("public", True) or not r.get("title"):
            continue
        try:
            age = (now - datetime.fromisoformat(r["published"].replace("Z", "+00:00"))).total_seconds() / 86400
        except Exception:
            continue
        rows.append({"제목": clean_t(r["title"]), "조회": int(r.get("views") or 0), "쇼츠": bool(r.get("short")), "경과일": age})
    only = c.get("anchor_type")   # 채널 주력 형식만(거대한비밀 = 쇼츠 — 초기 본편 실험은 형식 탓에 안 됐다)
    if only in ("쇼츠", "본편") and sum(1 for r in rows if r["쇼츠"] == (only == "쇼츠") and r["경과일"] >= 3) >= 5:
        rows = [r for r in rows if r["쇼츠"] == (only == "쇼츠")]
    if sum(1 for r in rows if r["경과일"] >= 3) >= 5:
        med = {s: statistics.median([r["조회"] for r in rows if r["쇼츠"] == s] or [1]) for s in (True, False)}
        for r in rows:
            r["배"] = round(r["조회"] / max(1.0, med[r["쇼츠"]]), 1)
            r["종류"] = "쇼츠" if r["쇼츠"] else "본편"
        rows = _uniq_titles(sorted(rows, key=lambda r: -r["배"]))
        top = [r for r in rows if r["경과일"] >= 1][:k]
        bot = [r for r in rows[::-1] if r["경과일"] >= 3 and r not in top][:k]
        return {"src": "우리 채널", "top": top, "bot": bot[::-1]} if top and bot else None
    # 같은 장르(또는 발굴) 영상: 조회수 순위와 평소 대비 배수 순위를 합쳐 줄 세운다(큰 채널의 평범한 편·작은 채널의 우연한 배수가 끝에 오지 않게)
    if eo and eo.get("pool"):
        pool, src, old_days = [dict(r) for r in eo["pool"] if r.get("평소대비") is not None], "같은 장르 채널 최근 60일 본편", 7
    else:
        pool = [dict(r) for kk in ("본편", "쇼츠") for r in (fob or {}).get(kk, []) if r.get("평소대비") is not None]
        src, old_days = "지금 뜨는 영상(발굴)", 0
    rv = {id(r): i for i, r in enumerate(sorted(pool, key=lambda r: -(r.get("조회") or 0)))}
    rm = {id(r): i for i, r in enumerate(sorted(pool, key=lambda r: -r["평소대비"]))}
    for r in pool:
        r["배"], r["_순위"] = r["평소대비"], rv[id(r)] + rm[id(r)]
    pool = _uniq_titles(sorted(pool, key=lambda r: r["_순위"]))
    top = pool[:k]
    bot = [r for r in pool[::-1] if (r.get("경과일") or 0) >= old_days and r not in top][:k]
    if not top or not bot:
        return None
    return {"src": src + "(우리 영상이 아직 적어서 대신)", "top": top, "bot": bot[::-1]}


def _uniq_titles(rows):
    """같은 제목(다시 올린 영상)은 앞의 것 하나만."""
    seen, out = set(), []
    for r in rows:
        key = _nz(r.get("제목"))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def sec_anchors(anc):
    """프롬프트용 기준점 줄."""
    if not anc:
        return []
    def row(r):
        extra = [f"평소의 {r['배']}배"] if r.get("배") is not None else []
        extra += [x for x in (r.get("종류"), r.get("갈래"), r.get("채널")) if x]
        return f"- {r['제목']} — {int(r.get('조회') or 0):,}회" + (f" ({' · '.join(extra)})" if extra else "")
    return (["", f"[hook 기준점 — {anc['src']}의 실제 성적. 새 소재의 hook 은 이 제목들과 견줘 매긴다]", "5점급 — 실제로 터진 편:"]
            + [row(r) for r in anc["top"]] + ["1점급 — 실제로 안 된 편:"] + [row(r) for r in anc["bot"]])


# ---------------------------------------------------------------- 재료: 이미 만든 편 · 최근 추천

def scan_done(c):
    """편 폴더 이름 → topics/done.json 사본. 예약 실행(launchd)은 맥 보안상 데스크톱을 못 읽어서 ~/.sojae 사본 저장소에서 돈다
    → 폴더가 안 보이면 사본을 쓴다. 사본은 데스크톱에서 돌 때(편 하나 끝날 때 비용_자동갱신.sh 가 --done-only 로 부름) 갱신된다."""
    names, days, seen_dirs = [], {}, False
    for d in c["episodes"]:
        p = (ROOT / d).resolve()
        try:
            if p.is_dir():
                for x in sorted(p.iterdir()):
                    if x.is_dir() and re.match(r"^\d", x.name):
                        nm = re.sub(r"^\d+[-_ ]*", "", x.name).replace("_", " ")
                        st = x.stat()   # 만든 날 = 편 폴더가 생긴 날(맥 st_birthtime, 없으면 수정 시각)
                        day = datetime.fromtimestamp(getattr(st, "st_birthtime", st.st_mtime), KST).strftime("%Y-%m-%d")
                        names.append(nm)
                        days[nm] = max(days.get(nm, ""), day)
                seen_dirs = True
        except PermissionError:
            pass
    dp = OUT / "done.json"
    done = json.loads(dp.read_text(encoding="utf-8")) if dp.exists() else {}
    if not seen_dirs:   # 예약 실행: 사본의 이름과 날짜("_dates" — 채널 이름 칸은 예전처럼 이름 목록만 둔다, collect.py 가 읽는다)
        _DONE_DAYS[c["name"]] = (done.get("_dates") or {}).get(c["name"], {})
        return done.get(c["name"], [])
    new = sorted(set(names))
    _DONE_DAYS[c["name"]] = days
    if done.get(c["name"]) != new or (done.get("_dates") or {}).get(c["name"]) != days:   # 바뀔 때만 쓴다(비용_자동갱신.sh 가 git diff 로 올릴지 정함)
        done[c["name"]] = new
        done.setdefault("_dates", {})[c["name"]] = days
        OUT.mkdir(exist_ok=True)
        dp.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    return new


_DONE_DAYS = {}   # 채널 → {편 폴더 이름: 만든 날} (scan_done 이 채운다)


def done_topics(c):
    """이미 만든 편 — ① 편 폴더(또는 done.json 사본) ② 우리 채널에 올라간 영상 제목 ③ 최근 7일 안에 만든 편(폴더·올린 영상·고른 소재)."""
    titles = [r.get("title") for r in (VIDEOS or {}).values() if r.get("ch") == c["name"] and r.get("title")]
    folders = scan_done(c)
    cut = (datetime.now(KST) - timedelta(days=MADE_DAYS)).strftime("%Y-%m-%d")
    made = [x for x in made_items(c) if x[1] >= cut]
    # 짧은 이름(편 폴더·고른 소재)으로 알린다. 폴더 날짜를 모를 때(예약 실행, 사본에 날짜 없음)만 올린 영상 제목으로
    recent = [n for n, _, k in made if k != "영상"] or [re.sub(r"\s+", " ", re.sub(r"#\S+", "", n)).strip()[:40] for n, _, k in made]
    return {"편_폴더": folders, "올린_영상_제목": titles[:80], "최근": list(dict.fromkeys(recent))}


def made_items(c):
    """이미 만든(또는 만들기로 고른) 편 [(이름, 'YYYY-MM-DD', 종류)] — 종류: 폴더(만든 날)·영상(공개일)·고름(picks.json 고른 날).
    폴더 날짜는 scan_done 이 채운 것(예약 실행은 done.json 사본의 _dates). 날짜를 모르면 '' (오래된 편으로 본다)."""
    if c["name"] not in _DONE_DAYS:
        scan_done(c)
    days = _DONE_DAYS.get(c["name"], {})
    dp = OUT / "done.json"
    folders = (json.loads(dp.read_text(encoding="utf-8")) if dp.exists() else {}).get(c["name"], []) or list(days)
    out = [(n, days.get(n, ""), "폴더") for n in dict.fromkeys(list(folders) + list(days))]
    for r in (VIDEOS or {}).values():
        if r.get("ch") == c["name"] and r.get("title"):
            try:
                day = datetime.fromisoformat(r["published"].replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d")
            except Exception:
                day = ""
            out.append((r["title"], day, "영상"))
    try:
        picks = json.loads(PICKS.read_text(encoding="utf-8")).get("items", []) if PICKS.exists() else []
    except Exception:
        picks = []
    for p in picks:
        if p.get("ch") == c["name"] and (p.get("대상") or p.get("소재")):
            out.append((p.get("대상") or p.get("소재"), str(p.get("picked_at") or "")[:10], "고름"))
    return out


MADE_STOP = {"쇼츠", "shorts", "본편", "후속", "샘플", "테스트", "최종", "수정", "대박"}
FU_STOP = {"만에", "이유", "지금", "진짜", "최초", "최대", "세계", "한국", "우리", "이번", "다시", "처음", "마지막", "그리고", "까지", "했을까",
           "됐을까", "어떻게", "무엇", "누가", "정말", "하는", "있는", "없는", "편의", "이야기", "사건"}


def _made_toks(s):
    return [_nz(w) for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", str(s or "").lower()) if w not in MADE_STOP]


def made_hit(t, made):
    """소재 t 가 이미 만든 편과 같은 대상인가(또는 그 편의 후속인가) → 가장 최근에 만든 (이름, 날짜), 아니면 None.
    같다고 보는 경우: 대상 이름이 편 폴더 이름·영상 제목·고른 소재에 들어 있다 / 편 폴더(짧은 이름)의 낱말이 모두 소재에 들어 있다
    (3글자 이상 낱말은 대상·소재·제목 어디든, 2글자 낱말은 대상 안에서만) / 후속 줄이 그 편을 가리킨다."""
    tgt = _nz(t.get("대상"))
    # '대우그룹(김우중)'·'A/B' 처럼 대상에 이름이 여럿이면 하나씩도 본다(2026-09-29 대우 후속이 통째 이름으로는 안 걸림)
    tgts = list(dict.fromkeys(x for x in [tgt] + [_nz(y) for y in re.split(r"[()（）\[\]/,·|]", str(t.get("대상") or ""))] if len(x) >= 2))
    text = _nz(" ".join(str(t.get(x) or "") for x in ("대상", "소재", "제목")))
    fu = _nz(t.get("후속"))
    fu_toks = [w for w in _made_toks(t.get("후속")) if not w[0].isdigit() and w not in FU_STOP]   # '5년'·'만에' 같은 흔한 조각은 빼고
    best = None
    for name, day, kind in made:
        nn, toks = _nz(name), _made_toks(name)
        short = kind in ("폴더", "고름")
        hit = any(g in nn for g in tgts) \
            or (short and toks and all((w in text) if len(w) >= 3 else (w in tgt) for w in toks))
        if not hit and fu_toks:   # 후속 줄: 그 편 이름 낱말이 후속에 다 있거나, 후속 낱말이 2개 이상(하나뿐이면 그 하나) 그 편에 있다
            hit = (short and toks and all(w in fu for w in toks)) or sum(1 for w in fu_toks if w in nn) >= min(2, len(fu_toks))
        if hit and (best is None or day > best[1]):
            best = (name, day)
    return best


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


# ---------------------------------------------------------------- 시장 수요(demand) — 유튜브 검색 실측(2026-09-29)
# 예전 근거(proof)는 AI가 '기사가 있다'로 채워 착공·적자·통계 같은 뉴스형이 위로 올라왔다. 이제 수요는 AI가 매기지 않는다:
# 소재마다 AI가 적은 검색어로 유튜브를 검색해 상위 15개의 조회수로 잰다(사람들이 이미 이 소재를 얼마나 찾아보나).
DEMAND_CACHE = OUT / "_demand_cache.json"
DEMAND_BLOCK = OUT / "_demand_block.json"   # 유튜브가 검색을 막은 시각 — 쉬는 동안은 검색하지 않는다
DEMAND_TTL = 7 * 86400        # 같은 검색어는 7일 안에 다시 검색하지 않는다
DEMAND_KEEP = 14 * 86400      # 새로 검색하지 못하면 14일 안의 지난 결과라도 쓴다
# 2026-09-29 같은 맥에서 유튜브 검색을 몰아서(동시 여러 개·수백 번) 하면 구글이 IP 를 '비정상 트래픽'(403·Sorry)으로 막아
# 유튜브 스튜디오 저장(공개 전환·설명)까지 실패했다(기억 ytdlp-bulk-blocks-studio). 그래서 한 번에 하나씩·간격을 두고·채널마다
# 한도까지만 검색하고, 막히면 그 자리에서 멈춘 뒤 몇 시간 쉰다.
DEMAND_GAP = (3.0, 5.0)       # 검색 사이 간격(초)
DEMAND_PER_CH = 20            # 채널마다 한 번 돌 때 새로 하는 검색 수 상한(AI 총점 높은 소재부터, 나머지는 캐시 또는 '생략')
DEMAND_COOLDOWN = 3 * 3600    # 막힌 뒤 검색을 쉬는 시간
DEMAND_IMPUTE = 1             # 못 잰 소재의 수요 — 낮게 둬서 잰 소재보다 앞서지 않게
DEMAND_TIERS = [1000000, 300000, 100000, 30000, 10000]   # 이만큼 이상이면 5·4·3·2·1, 못 미치면 0 (채널 설정 "demand": {"tiers"})
# 검색어에서 관련 영상을 가를 때 빼는 흔한 말(이 말만 겹치는 영상은 관련 없는 것으로 본다). 영어채널 검색어엔 거의 다 'South Korea'가
# 들어가서 그 말로는 못 가른다('SOUTH KOREA IS OVER' 1,576만 회가 어떤 한국 검색에도 걸림) → 한국·south·korea 도 뺀다.
DEMAND_STOP = {"한국", "서울", "seoul", "이유", "진짜", "영상", "다큐", "이야기", "정리", "역사", "최초", "세계", "최대", "사건", "괴담", "미스터리", "실화",
               "south", "korea", "korean", "koreans", "the", "and", "why", "how", "what", "is", "are", "was", "of", "in", "on", "to", "for",
               "its", "an", "this", "that", "with", "from", "by", "as", "at", "it", "be", "just", "now", "still", "new", "one", "two"}
_BLOCKED = [False]   # 이번 실행 중 유튜브가 막았는가


class Blocked(Exception):
    """유튜브가 검색을 막음(403·429·Sorry 페이지) — 더 두드리지 않는다."""


def _block_left():
    """유튜브가 막은 뒤 남은 쉬는 시간(초). 기록이 없거나 지났으면 0."""
    try:
        at = json.loads(DEMAND_BLOCK.read_text(encoding="utf-8")).get("at", 0)
    except Exception:
        return 0
    return max(0, at + DEMAND_COOLDOWN - time.time())


def _yt_page(q, n, gl):
    """유튜브 검색 결과 페이지(브라우저와 같은 주소)의 ytInitialData → [[조회수, 제목, 주소], …] 상위 n개.
    막히면(403·429·Sorry) Blocked, 그 밖의 실패는 None.
    2026-09-29 yt-dlp ytsearch(검색 API)가 403 으로 자주 막혀서(6번 중 4번) 결과 페이지를 먼저 쓴다."""
    url = "https://www.youtube.com/results?" + urllib.parse.urlencode({"search_query": q, "hl": "en", "gl": gl})
    hdr = dict(UA, **{"Accept-Language": "en-US,en;q=0.9", "Cookie": "CONSENT=YES+cb; SOCS=CAI"})
    try:
        resp = urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=20)
        if "/sorry" in resp.geturl():
            raise Blocked("Sorry 페이지")
        page = resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code}")
        return None
    except Blocked:
        raise
    except Exception:
        return None
    if "ytInitialData" not in page and "unusual traffic" in page.lower():
        raise Blocked("비정상 트래픽")
    m = re.search(r"(?:var ytInitialData|window\[\"ytInitialData\"\])\s*=\s*(\{.*?\});\s*</script>", page, re.S)
    try:
        data = json.loads(m.group(1)) if m else None
    except Exception:
        data = None
    if data is None:
        return None
    out, stack = [], [data]
    while stack and len(out) < n:   # 결과 순서대로(깊이 우선, 앞쪽부터)
        o = stack.pop()
        if isinstance(o, dict):
            vr = o.get("videoRenderer")
            if isinstance(vr, dict) and vr.get("videoId"):
                vc = vr.get("viewCountText") or {}
                txt = vc.get("simpleText") or "".join(x.get("text", "") for x in vc.get("runs", []))
                title = "".join(x.get("text", "") for x in (vr.get("title") or {}).get("runs", []))
                out.append([int(re.sub(r"\D", "", txt) or 0), title, "https://www.youtube.com/watch?v=" + vr["videoId"]])
                continue
            stack.extend(reversed(list(o.values())))
        elif isinstance(o, list):
            stack.extend(reversed(o))
    return out


def yt_search(q, n=15, gl="KR"):
    """유튜브 검색 결과 페이지 상위 n개 [[조회수, 제목, 주소], …]. 못 읽으면 None — '측정 못 함'(검색 결과 0개와 다르다).
    유튜브가 막으면 Blocked 를 그대로 올려 보낸다(부른 쪽이 검색을 멈춘다).
    2026-09-29 07시 yt-dlp ytsearch 가 403 을 내 네 채널 검색이 다 멈췄다 — yt-dlp 검색 창구는 결과 페이지보다 쉽게 막혀서 쓰지 않는다."""
    return _yt_page(q, n, gl)


def _on_topic(q, rows):
    """검색 결과 중 검색어의 낱말(흔한 말 빼고)이 제목에 든 영상만 — 광고·딴 영상 한 편이 수요를 부풀리지 않게."""
    toks = [_nz(w) for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", q.lower()) if w not in DEMAND_STOP]
    toks = [w for w in toks if len(w) >= 2]
    return [r for r in rows if any(w in _nz(r[1]) for w in toks)] if toks else rows


def demand_score(views, tiers):
    """조회수 목록 → 수요 0~5 = (최대 조회수 등급 + 상위 3개 중앙값 등급 × 2) ÷ 3 (반올림).
    한 편만 튄 검색(광고 영상 하나만 150만, 나머지는 1만대)은 낮게, 여러 편이 고르게 큰 소재는 높게."""
    v = sorted(views, reverse=True)
    if not v:
        return 0
    tier = lambda x: sum(1 for t in tiers if x >= t)
    return int((tier(v[0]) + 2 * tier(statistics.median(v[:3]))) / 3 + 0.5)


def measure_demand(c, topics):
    """소재마다 '검색어' 첫 번째(없으면 대상 이름)로 유튜브를 검색해 점수에 demand(0~5)를, 소재에 "수요"를 붙인다.
    같은 검색어 7일 캐시, 한 번에 하나씩 3~5초 간격, 채널마다 새 검색 DEMAND_PER_CH 개까지(topics 는 clean() 이 AI 총점순으로
    정렬해 둔 것이라 앞쪽부터 잰다). 유튜브가 막으면 그 자리에서 멈추고 DEMAND_COOLDOWN 동안 쉰다.
    못 잰 소재(한도·차단·실패)는 demand DEMAND_IMPUTE(낮게) — 못 잰 소재가 잰 소재를 앞지르지 않게."""
    conf = c.get("demand") or {}
    tiers, n = sorted(conf.get("tiers") or DEMAND_TIERS, reverse=True), int(conf.get("n", 15))
    gl = conf.get("gl") or ("US" if c.get("lang") == "en" else "KR")
    # 영어채널: 제목에 한국 고리(KOREA_RE)가 있는 영상만 센다 — 'child business owner' 같은 검색에 딴 나라 영상 6,562만 회가 걸렸다
    must = KOREA_RE if conf.get("must") == "korea" else (re.compile(conf["must"], re.I) if conf.get("must") else None)
    try:
        cache = json.loads(DEMAND_CACHE.read_text(encoding="utf-8")) if DEMAND_CACHE.exists() else {}
    except Exception:
        cache = {}
    now = time.time()
    key = lambda q: " ".join([gl, str(n)] + q.lower().split())
    qs = lambda t: ([q for q in (t.get("검색어") or []) if q][:1] or [x for x in [(t.get("대상") or t.get("소재") or "").strip()] if x])
    want = list(dict.fromkeys(q for t in topics for q in qs(t)))
    todo = [q for q in want if now - (cache.get(key(q)) or {}).get("at", 0) >= DEMAND_TTL]
    fresh = failed_q = 0
    stop = _BLOCKED[0] or _block_left() > 0
    if todo and stop:
        log(f"  유튜브 검색 쉬는 중(막힌 뒤 {DEMAND_COOLDOWN // 3600}시간) — 캐시만 쓴다")
    for i, q in enumerate(todo):
        if stop or i >= DEMAND_PER_CH:
            break
        if i:
            time.sleep(random.uniform(*DEMAND_GAP))
        try:
            rows = yt_search(q, n, gl)
        except Blocked as e:
            _BLOCKED[0] = stop = True
            try:
                DEMAND_BLOCK.write_text(json.dumps({"at": time.time(), "why": str(e)}, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            log(f"  ✘ 유튜브 검색이 막힘({e}) — 이번 실행은 검색을 멈추고 {DEMAND_COOLDOWN // 3600}시간 쉰다")
            break
        if rows is None:
            failed_q += 1
            continue
        cache[key(q)] = {"at": time.time(), "q": q, "r": rows}
        fresh += 1
    failed = 0
    for t in topics:
        rows, seen, ok = [], set(), False
        for q in qs(t):
            got = cache.get(key(q))
            if not got or now - got.get("at", 0) >= DEMAND_KEEP:
                continue
            ok = True
            for r in _on_topic(q, got["r"]):
                if must and not must.search(r[1]):
                    continue
                if r[2] not in seen:
                    seen.add(r[2])
                    rows.append(r)
        t.setdefault("점수", {})
        if not ok:
            t["점수"]["demand"] = DEMAND_IMPUTE
            t["수요"] = {"검색어": " | ".join(qs(t)), "측정": "생략"}
            failed += 1
            continue
        rows.sort(key=lambda r: -r[0])
        v = [r[0] for r in rows]
        t["점수"]["demand"] = demand_score(v, tiers)
        t["수요"] = {"검색어": " | ".join(qs(t)), "최대": v[0] if v else 0, "중앙": int(statistics.median(v[:3])) if v else 0,
                   "10만+": sum(1 for x in v if x >= 100000), "예시": [r[2] for r in rows[:2]]}
    try:
        cache = {k: x for k, x in cache.items() if now - x.get("at", 0) < DEMAND_KEEP}
        DEMAND_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log("수요 캐시 저장 실패", str(e)[:120])
    return {"검색어": len(want), "새로_검색": fresh, "검색_실패": failed_q, "측정_못함": failed, "막힘": _BLOCKED[0]}


# ---------------------------------------------------------------- 추천 정확도 보정(2026-09-26 사용자 요청)
# 우리 채널에 올린 영상을 같은 기준(조회수는 안 보여 주고 제목만)으로 AI가 채점 → 올린 뒤 3일 조회수와 비교해
# 어떤 기준이 실제 조회수와 잘 맞는지 재고, 가중치를 조금씩 옮긴다. AI가 매기는 점수만 보정하고,
# 수요(demand — 유튜브 검색 실측)는 고정(2026-09-29 근거 proof 를 대신함). 예전 채점(scored.json)에 hook 이 없으면 다시 채점한다.
FIT_KEYS = ("korea", "hook", "paradox", "visual")


def fit_keys(c):
    return [k for k in FIT_KEYS if k in c["scores"] and k in c["weights"]]


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
    """아직 채점 안 한 우리 영상(또는 새 점수 hook 이 없는 예전 채점)을 제목만 보고 채점(채널당 한 번에 최대 60편). 조회수는 절대 보여 주지 않는다."""
    v, fk = VIDEOS or {}, fit_keys(c)
    todo = [(vid, r["title"]) for vid, r in v.items() if r.get("ch") == c["name"] and r.get("title")
            and (vid not in scored or any(k not in (scored[vid].get("scores") or {}) for k in fk))][:60]
    if not todo or not fk:
        return 0
    sc = {k: c["scores"][k] for k in fk}
    prompt = (f"유튜브 채널 「{c['name']}」에 올린 영상 제목들이다. 조회수는 모른다고 치고, 제목과 소재만 보고 아래 기준으로 0~5 정수 채점하라.\n"
              + "\n".join(f"- {k}: {t}" for k, t in sc.items())
              + "\n[채널 공식]\n" + "\n".join(f"- {x}" for x in c["formula"][:3])
              + "\n도구를 쓰지 말고 JSON 하나만: {\"scores\": [{\"id\": \"영상 id\", " + ", ".join(f'"{k}": 0' for k in fk) + "}]}\n"
              + json.dumps([{"id": vid, "제목": t} for vid, t in todo], ensure_ascii=False))
    text, use = ask_claude(prompt, CFG.get("model", "sonnet"))
    log(c["name"], f"우리 영상 {len(todo)}편 채점 호출", tok_str(use))
    got = _json(text)
    n = 0
    for r in got.get("scores", []):
        if r.get("id") in v:
            scored[r["id"]] = {"ch": c["name"], "title": v[r["id"]]["title"], "at": datetime.now(KST).strftime("%Y-%m-%d"),
                               "scores": {k: max(0, min(5, int(r.get(k, 0) or 0))) for k in fk}}
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
    """실제 3일 조회수와 가장 잘 맞는 기준 쪽으로 가중치를 옮긴다. 데이터가 적을수록 원래 기준을 더 믿는다.
    AI 점수(fit_keys)만 옮기고 수요(demand)는 고정. 예전 채점에 없는 점수(hook)는 그 점수가 있는 영상만으로 잰다."""
    base = dict(c["weights"]); v = VIDEOS or {}; fk = fit_keys(c)
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
    # 형식 차이를 먼저 뺀다(2026-09-29): 거대한비밀 초기 본편은 제목과 상관없이 10~40회라 쇼츠와 섞으면 상관이 형식 탓으로 뒤집혔다
    fm = {}
    for f in (True, False):
        ys = [r[1] for r in rows if bool(v[r[2]].get("short")) == f]
        fm[f] = sum(ys) / len(ys) if ys else 0.0
    if len(fm) == 2 and all(any(bool(v[r[2]].get("short")) == f for r in rows) for f in fm):
        rows = [(r[0], r[1] - fm[bool(v[r[2]].get("short"))], r[2], r[3]) for r in rows]
    # 채널이 크는 추세(초기 영상은 뭘 해도 적게 나옴)를 빼고 비교: 조회수(log)를 올린 날짜로 직선 맞춘 뒤 남는 차이만 본다
    if len(rows) >= 3:
        ts, ys = [r[3] for r in rows], [r[1] for r in rows]
        mt, my = sum(ts) / len(ts), sum(ys) / len(ys)
        vt = sum((x - mt) ** 2 for x in ts)
        slope = sum((x - mt) * (y - my) for x, y in zip(ts, ys)) / vt if vt else 0.0
        rows = [(r[0], r[1] - (my + slope * (r[3] - mt)), r[2], r[3]) for r in rows]
    has = {k: [r for r in rows if k in r[0]] for k in fk}
    corr = {k: round(_corr([r[0][k] for r in has[k]], [r[1] for r in has[k]]), 2) for k in fk}
    # 부드럽게: 가중치 × (1 + α·상관). 상관이 약하면 거의 안 움직이고, 자료가 쌓일수록(α↑) 더 믿는다.
    # 사용자 기준(한국 인지도×3 등)을 소수 영상으로 뒤집지 않게 α 는 최대 0.6, 결과는 0.5~4.5 로 묶는다.
    w = dict(base); alpha = 0.0
    if len(rows) >= 6:
        alpha = min(0.6, len(rows) / (len(rows) + 20))
        for k in fk:
            m = len(has[k])
            if m >= 6:
                w[k] = round(min(4.5, max(0.5, base[k] * (1 + min(0.6, m / (m + 20)) * corr[k]))), 2)
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
    R = Refs()
    recent, overused = recent_brief(c["name"])
    ours, done = ours_brief(c["name"]), done_topics(c)
    kr_news = news(c["news"], per=c.get("news_per", 5), cap=c.get("news_cap", 100))
    en_news = news(c["news_en"], per=4, cap=40, sources=("google",), lang="en") if c.get("news_en") else []
    g, eo, fob, mats = c.get("genre"), None, None, []
    if g:   # 같은 장르 채널 훑기(영어채널·논스킵)
        eo = genre_outliers(genre_conf(g["file"]), KOREA_RE if g.get("filter") == "korea" else None)
        mats.append((g.get("label", "같은 장르 채널에서 지금 빨리 크는 영상(유튜브 RSS — 그 채널 평소 대비 배수·하루 조회수) · 공급"), sec_genre(eo, R)))
    if c.get("use_outliers", not g):   # 한국 유튜브 전체 발굴(채널 키워드로 줄임)
        fob = filter_outliers(ob, c)
        mats.append(("지금 한국 유튜브에서 평소보다 몇 배 빨리 크는 영상(발굴)", sec_outliers(fob, R)))
    mats += [("우리 채널 성적", sec_ours(ours, R)), ("이미 만든 편", sec_done(done)), ("최근 추천(반복 금지용)", sec_recent(recent)),
             (f"최신 한국 뉴스(최근 {NEWS_DAYS}일) — 타이밍 가산 재료일 뿐, 뉴스에 났다고 소재가 되지 않는다", sec_news(kr_news, R))]
    if en_news:
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
            "trend_n": len(trend), "outliers_at": eo["at"] if eo else ob.get("기준시각"),
            "genre_n": len(eo["hot"]) if eo else None, "genre_scanned": eo["scanned"] if eo else None,
            "genre_hot": [{k: r[k] for k in ("제목", "채널", "종류", "평소대비", "하루조회", "url")} for r in eo["hot"][:3]] if eo else None,
            "outliers_n": len(fob.get("쇼츠", [])) + len(fob.get("본편", [])) if fob else None,
            "ours_n": ours["편수"], "done_n": len(done["편_폴더"]), "often": [x["대상"] for x in recent["자주_나온_대상"]],
            "made_recent": done["최근"]}
    anc = anchors(c, eo, fob)
    info["anchors"] = {"src": anc["src"], "top": [f"{r['제목'][:40]} {int(r.get('조회') or 0):,}" for r in anc["top"]],
                       "bot": [f"{r['제목'][:40]} {int(r.get('조회') or 0):,}" for r in anc["bot"]]} if anc else None
    return {"mats": mats, "recent": recent, "calib": cal, "anchors": anc, "made_recent": done["최근"]}, allowed, dates, overused, info, R.by_id


def build_prompt(c, data):
    sc = c["scores"]; keys = list(sc); n = CFG["per_channel"]; ask = int(CFG.get("candidates", n + EXTRA))
    detail, en = CFG.get("detail_top", 8), c.get("lang") == "en"
    cal = data.get("calib") or {}
    n_cal = cal.get("n", 0)
    cal_line = ", ".join(f"{k} {v:+.2f}" for k, v in (cal.get("corr") or {}).items()) if n_cal >= 6 else "아직 자료 부족(6편 미만) — 기준표 그대로"
    rec = data["recent"]
    often = ", ".join(f"{x['대상']}({x['나온_횟수']}번)" for x in rec.get("자주_나온_대상", []))
    repeat_rule = (f"- 반복 금지(가장 중요): 최근 {rec.get('살펴본_추천_횟수', 0)}번의 추천에 자주 나온 대상 — {often}. 이 대상들은 각각 1개까지만, "
                   f"그것도 최근 {FRESH_DAYS}일 안의 새 기사나 지금 새로 터지는 영상이 근거일 때만 낸다. " if often else "- 반복 금지(가장 중요): ") + \
                  "공식에 예로 든 이름은 '이만큼 유명한 대상'이라는 뜻이다 — 이미 만든 편이나 최근 추천에 있는 이름이면 되풀이하지 말고 같은 급의 다른 대상을 찾고, 아직 만든 적 없는 이름이면 추천해도 된다."
    made = data.get("made_recent") or []
    made_rule = (f"- 이미 만든 편: 최근 {MADE_DAYS}일 안에 만든 편({' / '.join(made) if made else '없음'})의 대상과 그 후속은 내지 마라(프로그램이 뺀다). "
                 "그보다 오래된 만든 편과 같은 대상은 자극이 아주 클 때만 — 후속 줄에 그 편 이름(수요가 약하면 프로그램이 뺀다).")
    kinds = c.get("kinds") or {}   # 갈래(2026-09-28 논스킵 사건·괴담 믹스): 갈래마다 공식·최소 개수
    kind_block = []
    if kinds:
        more = max(2, (ask - n) // len(kinds))
        kind_block = ["", f"[갈래 — {ask}개 중 " + " · ".join(f"{k} 최소 {v.get('min', 0) + more}개" for k, v in kinds.items())
                      + f". 프로그램이 {n}개를 고를 때 갈래마다 " + " · ".join(f"{k} {v.get('min', 0)}개" for k, v in kinds.items())
                      + " 자리를 남기고 나머지는 총점순으로 채운다]"]
        for k, v in kinds.items():
            kind_block += [f"■ {k} — {v['desc']}"] + [f"- {x}" for x in v.get("formula", [])]
    wline = " · ".join(f"{k} ×{w:g}" for k, w in c["weights"].items())
    L = [f"너는 유튜브 채널 「{c['name']}」의 소재 기획자다. 아래 재료를 보고, 지금 만들면 조회수가 가장 크게 터질 자극적인 소재 후보 {ask}개를 골라라"
         f"(프로그램이 유튜브 검색으로 수요를 재고, 금지 유형·이미 만든 편·같은 대상 겹침을 걸러 {n}개를 쓴다).",
         "", "[채널 형식]", c["format"],
         "", "[떡상 공식 — 사용자 확정, 반드시 따른다]"] + [f"- {x}" for x in c["formula"]] + kind_block + [
         "", "[점수 기준 — 각 0~5 정수]"] + [f"- {k}: {v}" for k, v in sc.items()] + [
         "- demand(시장 수요)는 네가 매기지 않는다 — 프로그램이 '검색어' 줄로 유튜브를 검색해 상위 영상 조회수로 잰다.",
         f"- 총점 가중치: {wline} — hook(자극)과 demand(수요)가 가장 크다."] + sec_anchors(data.get("anchors")) + [
         "", f"[우리 채널 실측 — 올린 영상 {n_cal}편의 3일 조회수와 기준의 상관(1에 가까울수록 조회수와 잘 맞음)]", cal_line]
    if c.get("ban"):
        L += ["", "[금지 유형 — 내지 마라. 프로그램도 제목·대상·소재에 금지 말이 있으면 뺀다]"] + [f"- {x}" for x in c["ban"]]
    L += ["", "[규칙]",
          f"- 상대 채점(부풀리지 마라): hook 5 = 기준점 '5점급' 편과 맞먹는 자극, 3 = 보통, 1 = '1점급' 편 수준. hook 5 는 {ask}개 중 최대 3개. "
          f"모든 점수 항목은 {ask}개 평균이 3을 넘지 않게 매긴다(넘치면 프로그램이 답 순서 뒤쪽부터 깎는다).",
          "- 자극이 먼저다: 공포·비밀·극한·금기·돈·몰락·충격 반전·'이게 된다고?' — 제목만 보고 안 누르면 못 참는 소재. 소식·정보 전달형은 뒤로.",
          "- 뉴스·검색어는 '지금 다시 화제라 타이밍이 좋다'는 가산 재료일 뿐이다. 뉴스에 났다는 것만으로 소재가 되지 않는다"
          "(실적·공정률·통계·인사 발표 같은 소식 자체는 자극이 약하다). 자극·수요가 큰 소재가 마침 뉴스에 오르면 왜 줄에 타이밍을 적고 근거에 그 기사 번호를 단다.",
          "- 근거는 재료에 있는 번호(R…)만 쓴다. 지어내지 않는다. 근거가 없으면 근거 줄을 비워 둔다.",
          made_rule,
          "- 최근 추천과 같은 소재는 새 근거가 있을 때만 다시 낸다.",
          repeat_rule,
          f"- 다양성: {ask}개는 서로 다른 소재, 같은 대상은 2개까지. 섞어라 — ① 우리 대박 편(기준점 5점급)과 같은 결의 새 대상 "
          "② 지금 빨리 크는 영상에서 나온 소재 ③ 사람들이 오래 찾아보는 큰 소재(유튜브에 조회수 큰 영상이 이미 많은 것) ④ 아직 아무도 안 한 새 각도.",
          "- 사실 확인: 제목의 숫자·전제(층수·높이·금액·몇 번째)는 재료에 그대로 있을 때만 쓴다. 기사 속 숫자가 지금 있는 것인지 앞으로 지을·할 것인지 "
          "헷갈리면 제목에 쓰지 말고 확인 줄에 넣어라."]
    if c.get("genre"):
        L.append("- 같은 장르 채널 영상(재료 1)은 무엇이 먹히는지(장르·각도·제목 틀)를 보는 신호다. 그 채널들이 최근 60일 안에 다룬 사건·소재를 그대로 따라 하지 말고, 같은 대상이면 확실히 다른 각도일 때만 낸다.")
    if c.get("output_note"):
        L.append("- " + c["output_note"])
    L += ["", "[출력 형식 — JSON·설명·머리말 없이 아래 줄 형식만. 소재마다 '## '로 시작, 좋은 순서대로]",
          "## 소재 한 줄 이름",
          "대상: 핵심 대상 하나(건물·기업·인물·장소·제도의 가장 널리 쓰는 이름)"] + (
          [f"갈래: {' 또는 '.join(kinds)} 중 하나"] if kinds else []) + [
          f"점수: {' '.join(keys)} 순서로 0~5 정수 {len(keys)}개 (예: {' '.join(['3', '2', '4', '3', '2'][:len(keys)])})",
          "검색어: 사람들이 유튜브에서 이 소재를 찾을 때 실제로 칠 말 1~2개를 '|'로 나눠(대상 이름 + 핵심 낱말, 2~4 낱말" + (", 영어로" if en else "") + ")",
          "제목: 유튜브 제목 초안(#shorts 빼고)",
          "왜: 왜 터질까 — 무엇이 자극인지 2문장 이내(타이밍이 좋으면 한마디)",
          "근거: R번호 = 무엇이 근거인가(기사면 날짜) | R번호 = …   (R번호는 이 줄에만 쓴다. 왜·장면·확인 줄에는 쓰지 않는다)",
          "첫문장: 영상 첫 문장",
          "장면: 화면으로 무엇을 보여주나(1문장)",
          "확인: 제작 전 확인할 숫자·사실 | …(3개 이내)",
          "위험: 틀리거나 반려될 위험(1문장)",
          "후속: 우리 편의 후속이면 그 편 이름(아니면 이 줄 생략)",
          (f"갈래마다 가장 좋은 {max(1, detail // len(kinds))}개(모두 {max(1, detail // len(kinds)) * len(kinds)}개)는 모든 줄을 쓰고, 나머지 소재는 대상·갈래·점수·검색어·제목·왜(1문장)·근거 줄만 쓴다."
           if kinds else f"위에서 {detail}개는 모든 줄을 쓰고, 그 뒤 소재는 대상·점수·검색어·제목·왜(1문장)·근거 줄만 쓴다.")]
    for i, (label, text) in enumerate(data["mats"], 1):
        L += ["", f"[재료 {i} — {label}]", text]
    L += ["", f"오늘은 {datetime.now(KST).strftime('%Y-%m-%d')} 이다."]
    return "\n".join(L)


FIELD = {"대상": "대상", "제목": "제목", "첫문장": "첫문장", "왜": "왜_터질까", "왜_터질까": "왜_터질까",
         "장면": "보여줄_장면", "보여줄_장면": "보여줄_장면", "위험": "위험", "후속": "후속", "갈래": "갈래"}


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
            elif k == "검색어":   # 유튜브 수요를 잴 검색어 1~2개(2026-09-29)
                t["검색어"] = [x.strip().strip("'\"“”‘’`") for x in re.split(r"[|/;,]", v) if x.strip().strip("'\"“”‘’`")][:2]
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
        # 후보 30개(2026-09-29)부터 한 번에 9~11분 걸려서 15분 → 25분으로 늘림
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=1500, cwd=tmp)
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


REF_IN_TEXT = (re.compile(r"\s*[(\[]\s*R\d+(?:\s*[~,·\-–]\s*R?\d+)*\s*[)\]]"), re.compile(r"\bR\d+(?:\s*[~,·\-–]\s*R?\d+)*\b\s*"))


def strip_refs(x):
    """설명 글에 새어 나온 재료 번호(R12, (R3~R5))를 지운다 — 번호는 근거 줄에만 의미가 있다(2026-09-27)."""
    if isinstance(x, list):
        return [strip_refs(v) for v in x]
    if not isinstance(x, str):
        return x
    for rx in REF_IN_TEXT:
        x = rx.sub(" " if rx is REF_IN_TEXT[1] else "", x)
    return re.sub(r"\s{2,}", " ", x).strip()


def clean(c, got, allowed, dates=None):
    """AI 답 정리(후보 전부, 순서는 AI 답 그대로): AI 점수 0~5 정리(수요는 measure_demand 가 붙인다), 설명 글에 샌 R번호 지우기,
    지어낸 근거 주소 버림, 근거 기사 날짜로 '최신' 표시, 갈래."""
    ai_keys = list(c["scores"])
    dates, cut = dates or {}, fresh_cut()
    out = []
    for t in (got.get("topics", []) if isinstance(got, dict) else []):
        if not isinstance(t, dict) or not t.get("소재"):
            continue
        raw = t.get("점수") if isinstance(t.get("점수"), dict) else {}
        s = {}
        for k in ai_keys:
            try:
                s[k] = max(0, min(5, int(round(float(raw.get(k, 0) or 0)))))
            except (TypeError, ValueError):
                s[k] = 0
        t["점수"] = s
        if not isinstance(t.get("검색어"), list):
            t["검색어"] = [x.strip() for x in re.split(r"[|/;,]", str(t.get("검색어") or "")) if x.strip()][:2]
        for k in ("첫문장", "왜_터질까", "보여줄_장면", "확인할_사실", "위험"):   # 제목·소재는 건드리지 않는다
            if k in t:
                t[k] = strip_refs(t[k])
        for e in t.get("근거") or []:
            if isinstance(e, dict) and isinstance(e.get("메모"), str):
                e["메모"] = strip_refs(e["메모"])
        if c.get("kinds"):
            t["갈래"] = kind_of(c, t)
        t["근거"] = [e for e in (t.get("근거") or []) if isinstance(e, dict) and e.get("url") in allowed]   # 지어낸 주소는 버린다
        ds = sorted((dates[e["url"]] for e in t["근거"] if e["url"] in dates), reverse=True)
        t.pop("최신", None)
        if ds and ds[0] >= cut:
            t["최신"] = ds[0]      # 최근 14일 기사·검색어에 근거(대시보드 📰) — 타이밍 표시일 뿐 점수는 올리지 않는다
        out.append(t)
    return out


def tame_hook(topics, fives=3, mean_max=3.0):
    """hook(자극) 부풀림 깎기(2026-09-29 '점수는 높다는데 소재가 다 별로'): 5점은 답 순서대로 최대 3개(나머지 5는 4),
    그래도 평균이 3을 넘으면 답 순서 뒤쪽(AI가 덜 좋다고 본 소재)부터 한 바퀴씩 1점씩 깎는다(남긴 5점과 1점은 그대로). 돌려줌: 깎은 점수."""
    hs = [t for t in topics if isinstance((t.get("점수") or {}).get("hook"), int)]
    cut = 0
    for t in [t for t in hs if t["점수"]["hook"] == 5][fives:]:
        t["점수"]["hook"] = 4
        cut += 1
    excess = sum(t["점수"]["hook"] for t in hs) - mean_max * len(hs)
    while excess > 0:
        movable = [t for t in reversed(hs) if 1 < t["점수"]["hook"] < 5]
        if not movable:
            break
        for t in movable:
            if excess <= 0:
                break
            t["점수"]["hook"] -= 1
            excess -= 1
            cut += 1
    return cut


def finalize(c, topics, weights, overused=(), made=()):
    """수요까지 붙은 후보 → 총점(측정 못 한 항목은 빼고 정규화) · 금지 말 든 소재 빼기 · 이미 만든 편 거르기 ·
    같은 대상은 2개까지(최근 추천에 3번 이상 나온 대상은 1개) · 갈래 자리 → per_channel 개. 돌려줌: (소재들, 뺀 것 {까닭: [소재]})."""
    w = weights or c["weights"]
    ban = re.compile(c["ban_words"], re.I) if c.get("ban_words") else None
    cut = (datetime.now(KST) - timedelta(days=MADE_DAYS)).strftime("%Y-%m-%d")
    drop = {"금지 유형": [], f"최근 {MADE_DAYS}일 만든 편": [], "만든 편(자극·수요 약함)": [], "같은 대상": []}
    out = []
    for t in topics:
        s = t["점수"]
        have = [k for k in w if s.get(k) is not None]
        top = 5 * sum(w[k] for k in have)
        t["총점"] = round(sum(s[k] * w[k] for k in have) / top * 100) if top else 0
        name = t.get("소재")
        if ban and ban.search(" ".join(str(t.get(x) or "") for x in ("제목", "대상", "소재"))):
            drop["금지 유형"].append(name)
            continue
        hit = made_hit(t, made)
        t.pop("만든_편", None)
        if hit:
            if hit[1] >= cut:
                drop[f"최근 {MADE_DAYS}일 만든 편"].append(f"{name} ← {hit[0][:30]}")
                continue
            if not ((s.get("hook") or 0) >= 4 and (s.get("demand") or 0) >= 3):
                drop["만든 편(자극·수요 약함)"].append(f"{name} ← {hit[0][:30]}")
                continue
            t["만든_편"] = hit[0]   # 오래전에 만든 편과 같은 대상이지만 자극·수요가 커서 남김
        out.append(t)
    out.sort(key=lambda t: (-t["총점"], -(t["점수"].get("hook") or 0), 0 if t.get("최신") else 1))
    kept, seen = [], {}
    for t in out:
        k = _target(t)
        if k and seen.get(k, 0) >= (1 if k in overused else 2):
            drop["같은 대상"].append(t.get("소재"))
            continue
        seen[k] = seen.get(k, 0) + 1
        kept.append(t)
    if c.get("kinds"):   # 갈래마다 최소 개수 자리를 남기고 나머지는 총점순(2026-09-28 논스킵 사건·괴담 믹스)
        return keep_kinds(kept, CFG["per_channel"], {k: v.get("min", 0) for k, v in c["kinds"].items()}), drop
    return kept[:CFG["per_channel"]], drop


def kind_of(c, t):
    """답의 '갈래:' 줄 → 설정의 갈래 이름. 없거나 엉뚱하면 갈래별 match 말(소재·제목·대상)로 짐작, 그래도 없으면 첫 갈래."""
    kinds, g = c["kinds"], str(t.get("갈래") or "")
    for k in kinds:
        if k in g:
            return k
    text = " ".join(str(t.get(x) or "") for x in ("소재", "제목", "대상"))
    for k, v in kinds.items():
        if v.get("match") and re.search(v["match"], text, re.I):
            return k
    return next(iter(kinds))


PICKS = OUT / "picks.json"   # 만들기로 한 소재(2026-09-27 사용자: "여기서 몇 위 몇 위 만들어 달라고 하면")


def _nz(s):
    return re.sub(r"[\W_]+", "", str(s or "")).lower()


def resolve_channel(key):
    """채널 이름을 느슨하게 찾는다: 정확히 → 일부 → '영어'는 영어채널."""
    names = [c["name"] for c in CFG["channels"]]
    if key in names:
        return key
    k = _nz(key)
    hit = [n for n in names if k and k in _nz(n)]
    if not hit and k in ("영어", "영어채널", "paradox", "desk", "en"):
        hit = [c["name"] for c in CFG["channels"] if c.get("lang") == "en"]
    if len(hit) == 1:
        return hit[0]
    raise SystemExit(f"채널을 못 정했어요({key}) — 이 중에서: {', '.join(names)}")


def git_sync(paths=(), msg=None):
    """대시보드 기록과 맞추기: 먼저 받아 오고(순위가 대시보드와 같게), msg 가 있으면 paths 를 올린다. --no-push 면 아무것도 안 한다."""
    if "--no-push" in sys.argv:
        return True
    run = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    if msg:
        run("add", *[str(p) for p in paths])
        if run("diff", "--cached", "--quiet").returncode == 0:
            return True
        run("-c", "user.name=dashboard-bot", "-c", "user.email=dashboard-bot@users.noreply.github.com", "commit", "-q", "-m", msg)
    r = run("pull", "--rebase", "--autostash", "-q")
    ok = r.returncode == 0 and (not msg or run("push", "-q").returncode == 0)
    if not ok:
        log("! 대시보드와 맞추기 실패(다음에 다시):", (r.stderr or "")[:200])
    return ok


def load_picks():
    return json.loads(PICKS.read_text(encoding="utf-8")) if PICKS.exists() else {"next": 1, "items": []}


def find_topic(ch, key):
    """순위(대시보드 번호) 또는 이름 일부로 소재를 찾는다. 지금 목록 → 지난 추천(최근 것부터). 돌려줌: (소재, 순위, 추천 시각)"""
    latest = json.loads((OUT / "latest.json").read_text(encoding="utf-8")) if (OUT / "latest.json").exists() else {"channels": {}}
    cur = latest["channels"].get(ch) or {}
    topics = cur.get("topics") or []
    if str(key).isdigit():
        i = int(key) - 1
        if 0 <= i < len(topics):
            return topics[i], i + 1, cur.get("at")
        raise SystemExit(f"{ch} 지금 목록은 {len(topics)}위까지예요({key}위 없음)")
    k = _nz(key)
    for i, t in enumerate(topics):
        if k and k in _nz(" ".join(str(t.get(f) or "") for f in ("소재", "제목", "대상"))):
            return t, i + 1, cur.get("at")
    hp = OUT / "history.jsonl"
    runs = [json.loads(l) for l in hp.read_text(encoding="utf-8").splitlines() if l.strip()] if hp.exists() else []
    for r in reversed([r for r in runs if r.get("channel") == ch]):
        for i, t in enumerate(r.get("topics", [])):
            if k and k in _nz(" ".join(str(t.get(f) or "") for f in ("소재", "제목", "대상"))):
                return t, i + 1, r.get("at")
    raise SystemExit(f"{ch}에서 '{key}' 소재를 못 찾았어요")


def cmd_picks(args):
    """--pick 채널 순위|이름 … [--folder 편폴더] [--video 영상ID] · --link P번호 [--folder …] [--video …] · --unpick P번호 · --picks"""
    opt = lambda k: args[args.index(k) + 1] if k in args and args.index(k) + 1 < len(args) else None
    git_sync()                                   # 대시보드와 같은 순위를 보려고 먼저 받아 온다
    d, now, changed = load_picks(), datetime.now(KST).strftime("%Y-%m-%d %H:%M"), []
    if "--pick" in args:
        rest = args[args.index("--pick") + 1:]
        keys = []
        for x in rest[1:]:
            if x.startswith("--"):
                break
            keys.append(x)
        if not rest or not keys:
            raise SystemExit("쓰기: --pick 채널 순위|이름 …   예) --pick 거대한비밀 3 5")
        ch = resolve_channel(rest[0])
        c = next(x for x in CFG["channels"] if x["name"] == ch)
        known = scan_done(c)
        for key in keys:
            t, rank, at = find_topic(ch, key)
            if any(p["ch"] == ch and p["소재"] == t.get("소재") for p in d["items"]):
                log(f"이미 목록에 있어요: [{ch}] {t.get('소재')}"); continue
            item = {"id": f"P{d['next']}", "ch": ch, "picked_at": now, "rec_at": at, "rank": rank,
                    **{k: t.get(k) for k in ("소재", "제목", "대상", "총점", "최신", "첫문장", "왜_터질까", "근거", "확인할_사실")
                       if t.get(k) not in (None, "", [])},
                    "known_folders": known}
            for k in ("folder", "video"):
                if opt("--" + k):
                    item[k] = opt("--" + k)
            d["next"] += 1
            d["items"].append(item)
            changed.append(f"{item['id']} [{ch}] {rank}위 {t.get('소재')} (추천 {at})")
    for pid in [x for x in args if re.fullmatch(r"P\d+", x)] if ("--link" in args or "--unpick" in args) else []:
        it = next((p for p in d["items"] if p["id"] == pid), None)
        if not it:
            raise SystemExit(f"{pid} 가 목록에 없어요")
        if "--unpick" in args:
            d["items"].remove(it); changed.append(f"{pid} 뺌: [{it['ch']}] {it['소재']}")
        else:
            for k in ("folder", "video"):
                if opt("--" + k):
                    it[k] = opt("--" + k)
            changed.append(f"{pid} 연결: 폴더 {it.get('folder') or '-'} · 영상 {it.get('video') or '-'}")
    if changed:
        OUT.mkdir(exist_ok=True)
        PICKS.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        for x in changed:
            log(x)
        if "--no-push" in sys.argv:
            log("(--no-push: 대시보드에는 안 올림)")
        elif git_sync([PICKS, OUT / "done.json"], "만들기로 한 소재: " + " / ".join(x.split(" (")[0] for x in changed)[:120]):
            log("✔ 대시보드에 올림 — 10분 안에 🎯 소재 → 📋 제작 현황에 보여요")
    for p in d["items"]:
        print(f"  {p['id']:<4} [{p['ch']}] {p.get('rank')}위 {p['소재']} · 고른 날 {p['picked_at']}"
              + (f" · 폴더 {p['folder']}" if p.get("folder") else "") + (f" · 영상 {p['video']}" if p.get("video") else ""))
    if not d["items"]:
        print("  (만들기로 한 소재 없음)")


def main():
    args = sys.argv
    if any(k in args for k in ("--pick", "--unpick", "--link", "--picks")):
        return cmd_picks(args)
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
                log(name, f"재료: 장르 {info['genre_n'] if info['genre_n'] is not None else '-'}·발굴 {info['outliers_n'] if info['outliers_n'] is not None else '-'}, 우리 {info['ours_n']}편, "
                          f"만든 편 {info['done_n']}, 뉴스 {info['news_n']}(최근 {FRESH_DAYS}일 {info['fresh_news_n']}), 트렌드 {info['trend_n']}, "
                          f"자주 나온 대상 {info['often'] or '없음'}, 프롬프트 {len(prompt):,}자")
                # 재료는 늘 남긴다(깃에 안 올라감) — 답(topics/_answers/채널.txt)과 함께 `--answers topics/_answers` 로 AI 없이 다시 마무리할 수 있게
                mp.write_text(json.dumps({"at": now, "allowed": sorted(allowed), "dates": dates, "overused": sorted(overused), "info": info,
                                          "refs": refs}, ensure_ascii=False), encoding="utf-8")
                if dry:
                    (OUT / f"_prompt_{name}.txt").write_text(prompt, encoding="utf-8")
                    continue
                model = CFG.get("model", "sonnet")
                text, use = ask_claude(prompt, model)
                (OUT / "_answers").mkdir(exist_ok=True)
                (OUT / "_answers" / f"{name}.txt").write_text(text, encoding="utf-8")
                got = parse_answer(text, refs, list(c["scores"]))
            cands = clean(c, got, allowed, dates)
            tamed = tame_hook(cands)
            dm = measure_demand(c, cands)
            topics, dropped = finalize(c, cands, cal["weights"], overused, made_items(c))
            fresh_n = sum(1 for t in topics if t.get("최신"))
            kinds = {k: {"icon": v.get("icon", ""), "min": v.get("min", 0)} for k, v in (c.get("kinds") or {}).items()} or None
            labels = {k: (c.get("labels") or {}).get(k) or DEFAULT_LABELS.get(k, k) for k in c["weights"]}   # 총점 가중치 순서 = 대시보드 막대 순서
            latest["channels"][name] = {"at": at, "model": model, "outliers_at": info.get("outliers_at"), "news_n": info.get("news_n"),
                                        "trend_n": info.get("trend_n"), "fresh_n": fresh_n, "prompt_chars": info.get("prompt_chars"),
                                        "tokens": use, "labels": labels, "kinds": kinds, "genre_n": info.get("genre_n"), "genre_hot": info.get("genre_hot"),
                                        "candidates": len(cands), "demand": dm, "hook_cut": tamed, "anchors": info.get("anchors"),
                                        "dropped": {k: v for k, v in dropped.items() if v}, "topics": topics, "calib": view}
            with (OUT / "history.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": at, "channel": name, "topics": [{"소재": t.get("소재"), "대상": t.get("대상"), "제목": t.get("제목"),
                                                                            "총점": t["총점"], "점수": t.get("점수"), "최신": t.get("최신"),
                                                                            **({"갈래": t["갈래"]} if t.get("갈래") else {})}
                                                                           for t in topics]}, ensure_ascii=False) + "\n")
            log(name, f"후보 {len(cands)}개 · hook 깎음 {tamed} · 수요 검색어 {dm['검색어']}(새로 {dm['새로_검색']}·실패 {dm['검색_실패']}·측정 못 함 {dm['측정_못함']}) · 뺌",
                ", ".join(f"{k} {len(v)}" for k, v in dropped.items() if v) or "없음")
            log(name, "추천", len(topics), "개", tok_str(use), f"· 📰최신 {fresh_n}개 ·",
                *([" · ".join(f"{k} {sum(t.get('갈래') == k for t in topics)}개" for k in kinds), "·"] if kinds else []),
                " / ".join(f"{t.get('소재')} {t['총점']}(자극 {t['점수'].get('hook')}·수요 {t['점수'].get('demand')})" for t in topics[:6]), "…")
        except Exception as e:
            log(name, "실패 — 지난 추천 유지:", str(e)[:300])
            if name in latest["channels"]:
                latest["channels"][name]["stale"] = f"{now} 갱신 실패"
    if not dry:
        cp.write_text(json.dumps(calib_all, ensure_ascii=False, indent=1), encoding="utf-8")
        latest["at"] = now
        if trend:   # 대시보드 마케팅팀 회의에서 '지금 검색 급상승'으로 말한다(2026-09-27)
            latest["trends"] = [{"검색어": t["검색어"], "검색량": t["검색량"], "날짜": t["날짜"]} for t in trend[:10]]
        latest_p.write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
