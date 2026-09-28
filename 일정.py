#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""업로드 일정 모으기(2026-09-28 사용자: "각 채널별 예약발행 시간이랑 업로드일정 달력이나 표 같은 걸로 … 어떤게 어디까지 올라갔는지").

예약된 영상은 비공개라 API 키로는 안 보인다. 그래서 채널 폴더의 업로드 기록(업로드정보·업로드 결과 파일)에서
'영상 ID + 예약 시각'이 같은 줄에 적힌 곳을 모아 schedule.json 으로 만든다. collect.py 가 이것과 공개 영상 목록을 합쳐
📅 업로드 일정 화면을 그린다(공개되면 API 쪽 기록으로 바뀐다).
  · 올림  — 줄에 영상 ID가 있다(예약 또는 공개 완료).  예) [업로드 기록] 2026-09-28 예약 20:00 · 본편 rbPbFI0Cr0o · 쇼츠 5_ee0GreIwU
  · 계획  — '예약 + 날짜 시각'만 있고 ID가 없다(아직 안 올림). 같은 편·같은 종류가 올라가면 빠진다.

  python3 일정.py          모아서 schedule.json 저장(바뀐 경우만) + 요약
  python3 일정.py --show   저장하지 않고 찾은 것만 보여 주기
  python3 일정.py --push   바뀌었으면 커밋·푸시(대시보드에 10분 안에 반영)
  python3 일정.py --hook   PostToolUse 훅: 업로드 기록 파일을 쓰거나 업로드 명령을 돌렸을 때만 뒤에서 --push 를 띄우고 바로 끝낸다
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent            # 채널대시보드
BASE = ROOT.parent                                 # 유튜브 4채널
OUT = ROOT / "schedule.json"
LOG = ROOT / "일정_자동갱신.log"
PENDING = ROOT / ".일정.pending"
KST = timezone(timedelta(hours=9))
KEEP_DAYS = 14                                     # 이보다 오래된 기록은 버린다(공개된 건 API 쪽에 다 있다)

# 채널 폴더 → 대시보드 채널 이름(channels.json 의 name)
FOLDERS = {"거대한비밀": "거대한비밀", "거인의무덤": "거인의무덤", "논스킵": "논스킵", "영어채널": "The Paradox Desk",
           "시술백과": "시술백과", "필요한법": "필요한법"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "보관", "안쓰는파일", "venv", ".venv"}
NAME_RE = re.compile(r"업로드정보|업로드_?.*결과")
BAD_NAME = re.compile(r"_before|수정전")

ID = r"[A-Za-z0-9_-]{11}"
URL_RE = re.compile(r"(?:youtu\.be/|youtube\.com/shorts/|youtube\.com/watch\?v=|studio\.youtube\.com/video/)(" + ID + r")(?![A-Za-z0-9_-])")
LABEL_RE = re.compile(r"(본편|쇼츠)(\d?)[\s:|·=]*(" + ID + r")(?![A-Za-z0-9_-])")
DATE = r"(?<![\d-])(?:(20\d\d)-)?(\d\d)-(\d\d)(?:\s*\([^)]{1,3}\))?"      # 연도 없는 09-29 도 받는다(올해로)
TIME = r"(?:(오전|오후|낮|밤|저녁|새벽|아침)\s*)?(\d{1,2}):(\d\d)"
DT_RE = re.compile(DATE + r"\s*" + TIME)
SPLIT_RE = re.compile(DATE + r"\s*예약\s*" + TIME)           # 2026-09-28 예약 20:00
EP_RE = re.compile(r"^(\d{3})[-_ .]?(.*)$")
LINE_EP_RE = re.compile(r"^\W*(?:\d{1,2}:\d\d\s+)?(\d{3})\s+([^\s:|·—(]+)")
CANCEL_RE = re.compile(r"예약(을|은)?\s*(풀|취소|해제)|영구\s*삭제(했|함|완료)|삭제(했|함|완료)")
SEG_RE = re.compile(r"\s/\s")                                    # '… / 006 쇼츠 ID 예약 09-29 11:00 / …' 한 줄에 여러 건
SHORTS_HEAD = re.compile(r"^\s*(\[파일\]\s*쇼츠|\[쇼츠\d?\]|#+\s*쇼츠|■\s*쇼츠|=+\s*쇼츠)")
MAIN_HEAD = re.compile(r"^\s*(\[파일\]\s*본편|\[본편\]|#+\s*본편|■\s*본편|=+\s*본편)")


def now_kst():
    return datetime.now(KST)


def to_dt(y, mo, d, ampm, h, mi):
    h = int(h)
    if not y:
        now = now_kst()
        y = now.year + (1 if int(mo) < now.month - 6 else 0)
    if ampm in ("오후", "저녁", "밤") and h < 12:
        h += 12
    elif ampm == "낮" and h < 6:        # 낮 1시 = 13시
        h += 12
    elif ampm in ("오전", "새벽", "아침") and h == 12:
        h = 0
    try:
        return datetime(int(y), int(mo), int(d), h, int(mi))
    except ValueError:
        return None


def when(line, loose):
    """줄에서 공개(예약) 시각을 고른다. '예약' 바로 뒤 → 바로 앞 → (결과 파일 표 형식이면) 줄에 하나뿐인 시각."""
    m = SPLIT_RE.search(line)
    if m:
        return to_dt(*m.groups())
    cands = list(DT_RE.finditer(line))
    if not cands:
        return None
    for word in ("예약", "공개"):
        for k in re.finditer(word, line):
            after = [c for c in cands if 0 <= c.start() - k.end() <= 12]
            if after:
                return to_dt(*after[0].groups())
            before = [c for c in cands if 0 <= k.start() - c.end() <= 16]
            if before:
                return to_dt(*before[-1].groups())
    if loose and len(cands) == 1:
        return to_dt(*cands[0].groups())
    return None


def is_id(s):
    return bool(re.fullmatch(ID, s)) and not re.fullmatch(r"[a-z]+", s)


def ids_in(line):
    """줄에 나온 순서대로 [(ID, 종류, 번호)] — 번호는 '쇼츠2' 의 2. 종류를 모르면 None.
    주소 형식은 무조건, '본편/쇼츠 ID'·표(| ID |) 형식은 영문 소문자만인 낱말은 거른다."""
    out = {}
    for m in LABEL_RE.finditer(line):
        if is_id(m.group(3)):
            out.setdefault(m.group(3), (m.start(3), m.group(1), m.group(2)))
    for m in URL_RE.finditer(line):
        if m.group(1) not in out:
            head = line[max(0, m.start() - 24):m.start()]
            kind = "쇼츠" if "/shorts/" in m.group(0) or head.rfind("쇼츠") > head.rfind("본편") else "본편"
            out[m.group(1)] = (m.start(1), kind, "")
    if line.count("|") >= 3:                           # 표 형식: 006 박왕열 | 본편(새 파일) | NVWRu-KfEvo | 2026-09-29 11:00
        cells = [c.strip() for c in line.split("|")]
        kind = next((c[:2] for c in cells if c[:2] in ("본편", "쇼츠")), None)
        for c in cells:
            if is_id(c) and c not in out:
                out[c] = (line.find(c), kind, "")
    return [(vid, k, n) for vid, (_, k, n) in sorted(out.items(), key=lambda x: x[1][0])]


def episode(path, chdir):
    for p in path.relative_to(chdir).parents:
        m = EP_RE.match(p.name)
        if p.name and m:
            return m.group(1), (m.group(1) + " " + re.sub(r"[-_]+", " ", m.group(2))).strip()
    return None, None


def scan():
    occ, planned, cancelled = {}, [], set()           # occ[ID] = [(순서, 줄의 첫 ID인가, 기록)]
    files, labels = [], {}
    for folder, ch in FOLDERS.items():
        chdir = BASE / folder
        for dirpath, dirs, names in os.walk(chdir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for d in dirs:                             # 편 폴더 이름표: 006 → '006 박왕열드론탈옥'
                m = EP_RE.match(d)
                if m:
                    labels.setdefault((ch, m.group(1)), (m.group(1) + " " + re.sub(r"[-_]+", " ", m.group(2))).strip())
            for n in names:
                if NAME_RE.search(n) and not BAD_NAME.search(n) and n.endswith((".txt", ".md")):
                    p = Path(dirpath) / n
                    files.append((p.stat().st_mtime, p, ch, chdir))
    files.sort(key=lambda x: x[0])                    # 오래된 파일 먼저 → 나중 기록이 이긴다
    seq = 0
    for _, p, ch, chdir in files:
        num, label = episode(p, chdir)
        base_kind = "쇼츠" if "쇼츠" in p.name or p.parent.name == "쇼츠" else "본편"
        slot_no = (re.search(r"쇼츠(\d)", p.name) or [None, ""])[1]
        loose = "결과" in p.name
        section = base_kind
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        src = str(p.relative_to(BASE))
        for line in text.splitlines():
            if SHORTS_HEAD.match(line):
                section = "쇼츠"
            elif MAIN_HEAD.match(line):
                section = "본편"
            for seg in SEG_RE.split(line):
                if CANCEL_RE.search(seg):                  # '옛 006 본편 ID: … 예약을 풀어 비공개로' → 일정에서 뺀다
                    one = ids_in(seg)
                    if len(one) == 1:
                        cancelled.add(one[0][0])
                t = when(seg, loose)
                if not t:
                    continue
                seq += 1
                n2 = num
                if not n2:
                    m = LINE_EP_RE.match(seg)
                    n2 = m.group(1) if m else None
                ep = labels.get((ch, n2)) or label or p.parent.name
                ids = ids_in(seg)
                for i, (vid, kind, no) in enumerate(ids):
                    kind = kind or section
                    slot = kind + (no or (slot_no if kind == "쇼츠" else ""))
                    occ.setdefault(vid, []).append((seq, i == 0, {"id": vid, "ch": ch, "kind": kind, "slot": slot, "num": n2,
                                                                  "t": t.strftime("%Y-%m-%d %H:%M"), "ep": ep, "src": src}))
                if not ids and "예약" in seg:
                    kind = "쇼츠" if "본편과 같은" in seg else section
                    planned.append({"ch": ch, "kind": kind, "num": n2, "t": t.strftime("%Y-%m-%d %H:%M"), "ep": ep, "src": src})
    # 영상마다: 그 영상이 줄의 첫 ID(주어)인 기록 중 마지막 → 없으면 곁들여 나온 기록 중 마지막
    best = {}
    for vid, xs in occ.items():
        if vid in cancelled:
            continue
        s, first, x = ([x for x in xs if x[1]] or xs)[-1]
        if not x["num"]:                               # 편 번호가 없는 줄이면 같은 영상의 다른 줄에서
            num = next((o[2]["num"] for o in reversed(xs) if o[2]["num"]), None)
            if num:
                x = dict(x, num=num, ep=labels.get((x["ch"], num)) or x["ep"])
        best[vid] = (s, first, x)
    # 같은 편·같은 칸(본편/쇼츠/쇼츠2)에 ID가 여럿이면 가장 나중 기록만(지우고 다시 올린 영상)
    slots = {}
    for s, _, x in best.values():
        k = (x["ch"], x["num"] or x["ep"], x["slot"])
        if k not in slots or s > slots[k][0]:
            slots[k] = (s, x)
    up = [x for _, x in slots.values()]
    have = {(x["ch"], x["num"], x["kind"]) for x in up if x["num"]}
    times = {(x["ch"], x["t"]) for x in up}
    plan = {}
    for x in planned:
        if (x["ch"], x["num"], x["kind"]) in have or (x["ch"], x["t"]) in times:
            continue
        plan[(x["ch"], x["num"] or x["ep"], x["kind"])] = x   # 같은 편·종류는 마지막 기록만
    now = now_kst()
    cut_up = (now - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    cut_plan = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M")   # 지난 계획은 이틀만(놓친 칸 알림용)
    items = [dict(x, st="올림") for x in up if x["t"] >= cut_up] + [dict(x, st="계획") for x in plan.values() if x["t"] >= cut_plan]
    items = [{k: v for k, v in x.items() if k not in ("num", "slot")} for x in items]
    items.sort(key=lambda x: (x["t"], x["ch"], x["kind"]))
    return items


def save(items):
    old = {}
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    if old.get("items") == items:
        return False
    OUT.write_text(json.dumps({"at": now_kst().strftime("%Y-%m-%d %H:%M"), "items": items}, ensure_ascii=False, indent=1) + "\n",
                   encoding="utf-8")
    return True


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{now_kst():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass


def push():
    """schedule.json 만 커밋·푸시. 여러 대화가 동시에 부르면 폴더 잠금으로 한 번에 하나만."""
    lock = ROOT / ".일정.lock"
    for _ in range(60):
        try:
            lock.mkdir()
            break
        except FileExistsError:
            if time.time() - lock.stat().st_mtime > 300:   # 죽은 잠금
                lock.rmdir()
            time.sleep(1)
    else:
        log("✘ 잠금 대기 초과")
        return
    try:
        try:
            PENDING.unlink()                           # 이제부터 생기는 기록 변화는 다음 차례가 맡는다
        except OSError:
            pass
        items = scan()
        if not save(items):
            return
        git = lambda *a: subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True, timeout=120)
        git("add", "schedule.json")
        r = git("-c", "user.name=dashboard-bot", "-c", "user.email=dashboard-bot@users.noreply.github.com",
                "commit", "-q", "-m", f"업로드 일정 갱신 {now_kst():%Y-%m-%d %H:%M}", "--", "schedule.json")
        if r.returncode:
            log(f"✘ 커밋 실패 {r.stderr.strip()[:200]}")
            return
        for _ in range(3):
            if git("pull", "--rebase", "--autostash", "-q").returncode == 0 and git("push", "-q").returncode == 0:
                log(f"✔ 올림 ({len(items)}개)")
                return
            time.sleep(3)
        log("✘ 올리기 실패 — 다음 기록 때 다시 시도")
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


def show(items):
    by = {}
    for x in items:
        by.setdefault(x["ch"], []).append(x)
    for ch, xs in by.items():
        print(f"■ {ch}")
        for x in xs:
            print(f"  {x['t']}  {x['st']}  {x['kind']}  {x['ep']}  {x.get('id', '')}  ← {x['src']}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--hook":
        try:
            ti = json.loads(sys.stdin.read() or "{}").get("tool_input") or {}
        except ValueError:
            ti = {}
        # 업로드 기록 파일을 쓰거나 고쳤을 때, 또는 '업로드'가 들어간 명령(업로드 도구 등)을 돌렸을 때만
        hit = NAME_RE.search(Path(str(ti.get("file_path") or "")).name) or "업로드" in str(ti.get("command") or "")
        if hit and not (PENDING.exists() and time.time() - PENDING.stat().st_mtime < 120):   # 이미 한 번 줄 서 있으면 또 띄우지 않는다
            PENDING.touch()
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--push"], cwd=str(ROOT),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        sys.exit(0)
    items = scan()
    if arg == "--show":
        show(items)
    elif arg == "--push":
        push()
    else:
        changed = save(items)
        show(items)
        print(f"\n{len(items)}개 · {'schedule.json 저장' if changed else '바뀐 것 없음'}")
