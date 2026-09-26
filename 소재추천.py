#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""소재 추천기 — 하루 2번(한국시간 07·15시, 맥 launchd) '조회수 터질 만한 소재'를 AI가 판단해 대시보드 🎯 소재 탭에 올린다.

2026-09-26 사용자: "대시보드 시장조사를 하루 2번씩 조회수 빵빵 터질 만한 소재를 판단해서 가져오게" → 거대한비밀·거인의무덤, 내 맥, 07·15시.

입력(판단 재료 — 전부 프로그램이 모은다, AI 토큰 0):
  · 발굴 결과: gh-pages 의 data/outliers.json (발굴.py 가 06·14·21시에 찾은 '채널 평소보다 몇 배 빨리 크는 영상')
  · 우리 채널 성적: gh-pages 의 data/videos.json (무엇이 터졌고 무엇이 멈췄나)
  · 이미 만든 편: 각 채널 episodes 폴더 이름 (반복 금지)
  · 최신 뉴스: 빙 뉴스 RSS (요약문 포함, 키워드는 소재추천_기준.json)
  · 채널 공식·점수 기준: 소재추천_기준.json (사용자 확정 기준을 그대로 옮김, 바뀌면 이 파일만 고친다)
판단: `claude -p`(구독 안에서, 도구 없이 JSON 만) — 채널마다 1번.
출력: topics/latest.json (대시보드), topics/history.jsonl (나중에 추천 vs 실제 조회수 맞춰 보기)

쓰기:
  python3 소재추천.py                 # 두 채널 모두
  python3 소재추천.py --channel 거대한비밀
  python3 소재추천.py --dry           # 재료만 모아 프롬프트 크기 확인(AI 안 부름)
"""
import html
import json
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "topics"
KST = timezone(timedelta(hours=9))
CFG = json.loads((ROOT / "소재추천_기준.json").read_text(encoding="utf-8"))
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def log(*a):
    print(datetime.now(KST).strftime("%m-%d %H:%M:%S"), *a, flush=True)


def gh_json(name):
    """대시보드가 쌓아 둔 기록(gh-pages 브랜치 data/)을 읽는다. main 의 data/ 는 비어 있다."""
    try:
        raw = subprocess.run(["git", "show", f"origin/gh-pages:data/{name}"], cwd=ROOT, capture_output=True, check=True).stdout
        return json.loads(raw)
    except Exception as e:
        log("gh-pages 읽기 실패", name, str(e)[:120])
        return None


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


def ours_brief(ch):
    v = gh_json("videos.json") or {}
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


def done_topics(c):
    """이미 만든 편 — ① 편 폴더 이름(데스크톱에서 돌 때만 보임) ② 우리 채널에 올라간 영상 제목 ③ topics/done.json(폴더를 못 볼 때 쓰는 사본).
    예약 실행(launchd)은 맥 보안상 데스크톱을 못 읽어서 ~/.sojae 사본 저장소에서 돈다 → ①이 비면 ③을 쓴다."""
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
    if seen_dirs:
        done[c["name"]] = sorted(set(names)); dp.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        names = done.get(c["name"], [])
    v = gh_json("videos.json") or {}
    titles = [r.get("title") for r in v.values() if r.get("ch") == c["name"] and r.get("title")]
    return {"편_폴더": sorted(set(names)), "올린_영상_제목": titles[:80]}


def news(keywords, per=6, days=45):
    """빙 뉴스 RSS — 제목·요약·원문 주소. (WebSearch 한도와 무관, 2026-09-26 확인)"""
    out, seen = [], set()
    cut = datetime.now(timezone.utc) - timedelta(days=days)
    for kw in keywords:
        url = "https://www.bing.com/news/search?format=rss&q=" + urllib.parse.quote(kw)
        try:
            x = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read().decode("utf-8", "ignore")
        except Exception as e:
            log("뉴스 실패", kw, str(e)[:80]); continue
        n = 0
        for item in re.findall(r"<item>(.*?)</item>", x, re.S):
            g = lambda tag: html.unescape((re.search(rf"<{tag}>(.*?)</{tag}>", item, re.S) or [None, ""])[1]).strip()
            title, link, desc, pub = g("title"), g("link"), re.sub(r"<[^>]+>", "", g("description")), g("pubDate")
            real = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("url", [link])[0]
            try:
                when = parsedate_to_datetime(pub)
                if when < cut: continue
                pub = when.astimezone(KST).strftime("%Y-%m-%d")
            except Exception:
                pass
            key = re.sub(r"\W", "", title)[:40]
            if not title or key in seen: continue
            seen.add(key); out.append({"검색어": kw, "날짜": pub, "제목": title, "요약": desc[:220], "url": real}); n += 1
            if n >= per: break
    return out


def history(ch, runs=6):
    p = OUT / "history.jsonl"
    if not p.exists(): return []
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("channel") == ch][-runs:]
    return sorted({t["소재"] for r in rows for t in r.get("topics", [])})


def build_prompt(c, data):
    sc = c["scores"]; n = CFG["per_channel"]
    schema = {"topics": [{"소재": "한 줄 이름", "제목": "유튜브 제목 초안(#shorts 빼고)", "첫문장": "영상 첫 문장",
                          "왜_터질까": "2~3문장, 아래 근거를 짚어서", "근거": [{"url": "재료에 있는 주소만", "메모": "무엇이 근거인가"}],
                          "점수": {k: "0~5 정수" for k in sc}, "보여줄_장면": "화면으로 무엇을 보여주나",
                          "확인할_사실": ["제작 전 꼭 확인할 숫자·사실"], "위험": "틀리거나 반려될 위험", "후속": "우리 대박 편의 후속이면 그 편 이름, 아니면 빈 문자열"}]}
    return f"""너는 유튜브 채널 「{c['name']}」의 소재 기획자다. 아래 재료만 보고, 지금 만들면 조회수가 가장 크게 터질 소재 {n}개를 골라라.

[채널 형식]
{c['format']}

[이 채널의 떡상 공식 — 사용자 확정, 반드시 따른다]
""" + "\n".join(f"- {x}" for x in c["formula"]) + f"""

[점수 기준 — 각 0~5 정수]
""" + "\n".join(f"- {k}: {v}" for k, v in sc.items()) + f"""

[규칙]
- 근거 url 은 아래 재료(발굴 영상·뉴스·우리 영상)에 실제로 있는 주소만 쓴다. 지어내지 않는다. 근거가 약하면 proof 점수를 낮게 준다.
- 이미 만든 편과 같은 소재는 빼라(다른 각도의 후속은 된다, '후속' 칸에 적기).
- 최근 추천과 같은 소재는 새 근거가 있을 때만 다시 낸다.
- 확인 안 된 숫자는 제목에 쓰지 말고 '확인할_사실'에 넣어라.
- 도구를 쓰지 말고, 설명 없이 아래 형식의 JSON 하나만 출력하라.

[출력 형식]
{json.dumps(schema, ensure_ascii=False)}

[재료 1 — 지금 유튜브에서 평소보다 몇 배 빨리 크는 영상(발굴)]
{json.dumps(data['outliers'], ensure_ascii=False)}

[재료 2 — 우리 채널 성적]
{json.dumps(data['ours'], ensure_ascii=False)}

[재료 3 — 이미 만든 편]
{json.dumps(data['done'], ensure_ascii=False)}

[재료 4 — 최근 추천했던 소재]
{json.dumps(data['recent'], ensure_ascii=False)}

[재료 5 — 최신 뉴스(최근 45일)]
{json.dumps(data['news'], ensure_ascii=False)}

오늘은 {datetime.now(KST).strftime('%Y-%m-%d')} 이다.
"""


def ask_claude(prompt, model):
    with tempfile.TemporaryDirectory() as tmp:   # 프로젝트 문서를 읽어 들이지 않게 빈 폴더에서 부른다
        r = subprocess.run(["claude", "-p", "--output-format", "json", "--model", model, "--max-turns", "1"],
                           input=prompt, capture_output=True, text=True, timeout=900, cwd=tmp)
    if r.returncode != 0:
        raise RuntimeError(f"claude 실패 {r.returncode}: {(r.stderr or r.stdout)[:300]}")
    env = json.loads(r.stdout); text = env.get("result") or ""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if not m:
        raise RuntimeError("JSON 없음: " + text[:300])
    return json.loads(m.group(1)), env.get("total_cost_usd")


def clean(c, got, allowed):
    w = c["weights"]; top = 5 * sum(w.values())
    out = []
    for t in got.get("topics", []):
        s = {k: max(0, min(5, int(round(float((t.get("점수") or {}).get(k, 0) or 0))))) for k in w}
        t["점수"] = s
        t["총점"] = round(sum(s[k] * w[k] for k in w) / top * 100)
        t["근거"] = [e for e in (t.get("근거") or []) if isinstance(e, dict) and e.get("url") in allowed]   # 지어낸 주소는 버린다
        out.append(t)
    out.sort(key=lambda t: -t["총점"])
    return out[:CFG["per_channel"]]


def main():
    only = sys.argv[sys.argv.index("--channel") + 1] if "--channel" in sys.argv else None
    dry = "--dry" in sys.argv
    subprocess.run(["git", "fetch", "-q", "origin", "gh-pages"], cwd=ROOT)
    OUT.mkdir(exist_ok=True)
    latest_p = OUT / "latest.json"
    latest = json.loads(latest_p.read_text(encoding="utf-8")) if latest_p.exists() else {"channels": {}}
    ob = outliers_brief()
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    for c in CFG["channels"]:
        if only and c["name"] != only: continue
        data = {"outliers": ob, "ours": ours_brief(c["name"]), "done": done_topics(c), "recent": history(c["name"]), "news": news(c["news"])}
        allowed = {r["url"] for k in ("쇼츠", "본편", "뜨는채널") for r in ob.get(k, []) if r.get("url")}
        allowed |= {r["url"] for k in ("잘된_영상", "안된_영상") for r in data["ours"][k]} | {r["url"] for r in data["news"]}
        prompt = build_prompt(c, data)
        log(c["name"], f"재료: 발굴 쇼츠 {len(ob['쇼츠'])}·본편 {len(ob['본편'])}, 우리 {data['ours']['편수']}편, 만든 편 {len(data['done']['편_폴더'])}, 뉴스 {len(data['news'])}, 프롬프트 {len(prompt):,}자")
        if dry:
            (OUT / f"_prompt_{c['name']}.txt").write_text(prompt, encoding="utf-8"); continue
        try:
            got, cost = ask_claude(prompt, CFG.get("model", "sonnet"))
            topics = clean(c, got, allowed)
            latest["channels"][c["name"]] = {"at": now, "model": CFG.get("model"), "outliers_at": ob.get("기준시각"), "news_n": len(data["news"]), "topics": topics}
            with (OUT / "history.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": now, "channel": c["name"], "topics": [{"소재": t.get("소재"), "제목": t.get("제목"), "총점": t["총점"]} for t in topics]}, ensure_ascii=False) + "\n")
            log(c["name"], "추천", len(topics), "개", f"(${cost:.2f})" if cost else "", "·", " / ".join(f"{t.get('소재')} {t['총점']}" for t in topics))
        except Exception as e:
            log(c["name"], "실패 — 지난 추천 유지:", str(e)[:300])
            if c["name"] in latest["channels"]:
                latest["channels"][c["name"]]["stale"] = f"{now} 갱신 실패"
    if not dry:
        latest["at"] = now
        latest_p.write_text(json.dumps(latest, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
