#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2D 픽셀 사무실 그림 만들기 (2026-09-27 사용자: "실사이미지로 했는데.2d 캐릭터로 바꾸고.. 막움직이면서 진짜 사무실돌아다니는느낌으로")

그림 출처(공개 저장소에 올려도 되는 것만):
  - Pixel Agents (MIT, https://github.com/pixel-agents-hq/pixel-agents) — 가구·바닥·벽·캐릭터·고양이 그림
  - 캐릭터 바탕은 JIK-A-4 Metro City (CC0, https://jik-a-4.itch.io/metrocity-free-topdown-character-pack)
  - 창문·정수기·복합기·커피 카운터·자판기·TV 는 이 파일이 직접 그린다
만드는 것(staff/):
  office.png      캐릭터 7명(담당 색 옷) + 가구 + 직접 그린 소품을 한 장에 모은 그림
  office_bg.png   바닥·바깥 벽·벽 장식을 미리 그린 배경(창문 유리는 비워 둠 → 화면이 시간대별 하늘을 그림)
                  안쪽 벽(일하는 곳 | 회의실 / 휴게실)은 office.json 가구 목록에 벽 조각으로 들어가 사람과 앞뒤를 가려 그린다
  office.json     칸 지도·가구 위치·앉는 자리·들르는 곳·창문/시계/화이트보드/TV 자리
  face_<키>.png   각 화면 위 얼굴(픽셀 캐릭터 머리)
  LICENSE-office-art.txt  그림 저작권 문구(MIT)
쓰기: python3 직원그림/make_office.py [--preview /tmp/office_preview.png]
원본이 없으면 고정 커밋에서 받아 온다(직원그림/원본_pixel-agents/, 깃에는 안 올림)."""
import colorsys
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = HERE / "원본_pixel-agents"
COMMIT = "3537e140c2094761beae748592aeb92ece8edfdd"   # pixel-agents-hq/pixel-agents main, 2026-09-21
RAW = f"https://raw.githubusercontent.com/pixel-agents-hq/pixel-agents/{COMMIT}/"
ASSETS = "webview-ui/public/assets/"
OUT = ROOT / "staff"
T = 16                       # 타일 한 칸(픽셀)
COLS, ROWS = 24, 16          # 사무실 크기(칸) → 384×256 픽셀. 아이폰(390pt@3x)에서 정확히 3배
FURN = ["BIN", "CACTUS", "CLOCK", "COFFEE", "COFFEE_TABLE", "CUSHIONED_BENCH", "CUSHIONED_CHAIR/CUSHIONED_CHAIR_BACK",
        "CUSHIONED_CHAIR/CUSHIONED_CHAIR_FRONT", "CUSHIONED_CHAIR/CUSHIONED_CHAIR_SIDE", "DESK/DESK_FRONT", "DOUBLE_BOOKSHELF",
        "BOOKSHELF", "HANGING_PLANT", "LARGE_PAINTING", "LARGE_PLANT", "PC/PC_BACK", "PC/PC_FRONT_OFF", "PC/PC_FRONT_ON_1",
        "PC/PC_FRONT_ON_2", "PC/PC_FRONT_ON_3", "PLANT", "PLANT_2", "POT", "SMALL_PAINTING", "SMALL_PAINTING_2",
        "SMALL_TABLE/SMALL_TABLE_FRONT", "SOFA/SOFA_BACK", "SOFA/SOFA_FRONT", "SOFA/SOFA_SIDE", "TABLE_FRONT", "WHITEBOARD",
        "WOODEN_CHAIR/WOODEN_CHAIR_BACK", "WOODEN_CHAIR/WOODEN_CHAIR_SIDE"]


# ───────────────────────── 원본 받기 ─────────────────────────
def need_files():
    fs = ["LICENSE", ASSETS + "walls/wall_0.png", ASSETS + "pets/gitcat/pet.png"]
    fs += [ASSETS + f"characters/char_{i}.png" for i in range(6)] + [ASSETS + f"floors/floor_{i}.png" for i in range(9)]
    for f in FURN:
        d, n = (f.split("/") + [f])[:2] if "/" in f else (f, f)
        fs.append(ASSETS + f"furniture/{d}/{n}.png")
    return fs


def ensure_src():
    for rel in need_files():
        p = SRC / rel
        if p.exists():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        print("받기", rel)
        with urllib.request.urlopen(RAW + rel, timeout=60) as r:
            p.write_bytes(r.read())


def img(rel):
    return Image.open(SRC / ASSETS / rel).convert("RGBA")


def furn(name):
    d, n = name.split("/") if "/" in name else (name, name)
    return img(f"furniture/{d}/{n}.png")


# ───────────────────────── 색 ─────────────────────────
def hx(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def colorize(im, h, s, b, c):
    """Pixel Agents colorize.ts 와 같은 방식: 밝기만 남기고(회색) 색상 h·채도 s 를 입힌다. c=대비, b=밝기(-100~100)."""
    out = im.copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, bb, a = px[x, y]
            if a == 0:
                continue
            l = (0.299 * r + 0.587 * g + 0.114 * bb) / 255
            if c:
                l = 0.5 + (l - 0.5) * (100 + c) / 100
            if b:
                l += b / 200
            l = max(0.0, min(1.0, l))
            rr, gg, b2 = colorsys.hls_to_rgb(h / 360, l, s / 100)
            px[x, y] = (round(rr * 255), round(gg * 255), round(b2 * 255), a)
    return out


def recolor(im, mapping, region=None):
    """정해 둔 색만 바꾼다. region(x, y) — 캐릭터 한 칸(16×32) 안 좌표 조건(예: 몸통만)."""
    m = {hx(k): hx(v) for k, v in mapping.items()}
    out = im.copy()
    px = out.load()
    for y in range(out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a and (r, g, b) in m and (region is None or region(x % 16, y % 32)):
                px[x, y] = m[(r, g, b)] + (a,)
    return out


# 직원 7명 = 캐릭터 7명. 옷 색 = 대시보드 담당 색(collect.py STAFF color). 머리색은 짙게(한국 팀 느낌)
BODY = lambda x, y: y >= 14
DRESS = lambda x, y: 15 <= y <= 27
CHARS = {
    "lead": (0, [({"114978": "4b3fb0", "0f406a": "3b3192", "071c2e": "1f1a4f", "1164a9": "6c5ce7"}, None),
                 ({"8f6439": "3e2d25", "6d4726": "2b1f1a", "6f4a2a": "2e211c", "b18649": "5b4437"}, None)]),
    "analyst": (5, [({"b24737": "2b6de0", "e16451": "5d95f3", "9f3f31": "2258bd", "640026": "17306d"}, None)]),
    "reviewer": (2, [({"f67d20": "e0392b", "e1721d": "c22f23", "e8741b": "cf3427", "e87218": "cb3125", "ff8b31": "f45b4b", "592700": "5b0f0c"}, None),
                     ({"5f4132": "c98e6b", "493227": "a56d51", "593b2c": "b77c5d", "75503d": "d89c78", "865e4c": "e4ab88"}, None)]),
    "trend": (1, [({"252525": "ef7a1c", "101010": "9f4b0b", "2b2b2b": "ff9b45", "1a1a1a": "c75f12"}, DRESS)]),
    "planner": (4, [({"d4d4d4": "1f9d6b", "eeeeee": "4cc38f", "bdbdbd": "178359", "4c4c4c": "0e4b33"}, BODY),
                    ({"432415": "2c1b13", "2f160f": "1d110b", "57351a": "3d2619", "69451b": "4f3423", "442414": "2d1c14"}, None)]),
    "scheduler": (0, [({"114978": "008a8a", "0f406a": "006b6d", "071c2e": "003739", "1164a9": "19b8b3"}, None),
                      ({"8f6439": "2c2826", "6d4726": "1c1918", "6f4a2a": "1f1b1a", "b18649": "403a37"}, None)]),
    "money": (3, [({"d4d4d4": "d4a106", "eeeeee": "f3c945", "bdbdbd": "b08604", "4c4c4c": "6b5203"}, BODY),
                  ({"b0a6a3": "3d2b24", "daccc9": "5c4135", "bfb6b3": "47342b", "f0e1de": "6d4e3f", "fff1ef": "7c5b4a", "e9d7d4": "654839"}, None)]),
}
ORDER = ["lead", "analyst", "reviewer", "trend", "planner", "scheduler", "money"]


def make_chars():
    out = {}
    for k in ORDER:
        base, steps = CHARS[k]
        im = img(f"characters/char_{base}.png")
        for mapping, region in steps:
            im = recolor(im, mapping, region)
        out[k] = im
    return out


# ───────────────────────── 직접 그리는 소품 ─────────────────────────
def canvas(w, h):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def R(d, x0, y0, x1, y1, col):
    d.rectangle((x0, y0, x1, y1), fill=hx(col) + (255,))


def P(d, x, y, col):
    d.point((x, y), fill=hx(col) + (255,))


def sp_window():
    """벽 창문 32×32 — 유리(4..27, 12..25)는 투명. 화면이 시간대 하늘을 먼저 칠한다."""
    im, d = canvas(32, 32)
    R(d, 1, 9, 30, 28, "1b2130")
    R(d, 2, 10, 29, 27, "dfe6ee")
    R(d, 3, 11, 28, 26, "aab6c6")
    R(d, 4, 12, 27, 25, "000000")
    R(d, 15, 12, 16, 25, "dfe6ee"); R(d, 4, 18, 27, 19, "dfe6ee")
    P(d, 16, 12, "aab6c6"); R(d, 4, 19, 27, 19, "aab6c6")
    R(d, 0, 26, 31, 27, "f1f5f9"); R(d, 0, 28, 31, 28, "7d8a9c"); R(d, 0, 29, 31, 29, "1b2130")
    px = im.load()
    for y in range(12, 26):
        for x in range(4, 28):
            if px[x, y][:3] == (0, 0, 0):
                px[x, y] = (0, 0, 0, 0)
    return im


def sp_cooler():
    im, d = canvas(16, 32)
    R(d, 4, 3, 11, 14, "2b4a66"); R(d, 5, 4, 10, 13, "8fcbef"); R(d, 5, 4, 6, 12, "d6efff"); R(d, 9, 5, 10, 13, "6aaed8")
    R(d, 6, 14, 9, 15, "4f7fa6")
    R(d, 3, 16, 12, 30, "3a3f4a"); R(d, 4, 17, 11, 29, "e8edf2"); R(d, 10, 17, 11, 29, "c3ccd6")
    R(d, 5, 20, 10, 23, "3a3f4a"); R(d, 6, 21, 9, 22, "6b7280"); P(d, 6, 20, "e0392b"); P(d, 9, 20, "2b6de0")
    R(d, 4, 26, 11, 26, "c3ccd6"); R(d, 3, 31, 12, 31, "1c1f26")
    return im


def sp_printer(frame):
    """복합기 32×32. frame 0 보통, 1 종이가 나옴, 2 불빛 깜빡"""
    im, d = canvas(32, 32)
    R(d, 2, 9, 29, 30, "2a2f3a"); R(d, 3, 10, 28, 29, "c9ced6"); R(d, 3, 25, 28, 29, "a3aab5")
    R(d, 3, 6, 28, 10, "2a2f3a"); R(d, 4, 7, 27, 9, "8d95a1"); R(d, 4, 7, 27, 7, "e5e9ee")
    R(d, 6, 12, 19, 14, "3b404b")
    R(d, 21, 12, 27, 18, "2e3440"); R(d, 23, 13, 26, 15, "6fb7ff" if frame != 2 else "a9d6ff")
    P(d, 22, 17, "3ddc84" if frame != 2 else "1f6b43")
    R(d, 4, 20, 27, 20, "8b929e"); R(d, 4, 24, 27, 24, "8b929e"); R(d, 11, 22, 18, 22, "5b616c"); R(d, 11, 26, 18, 26, "5b616c")
    if frame == 1:
        R(d, 8, 9, 17, 13, "ffffff"); R(d, 9, 10, 15, 10, "c7ced8"); R(d, 9, 12, 14, 12, "c7ced8")
    return im


def sp_cafe():
    """커피 카운터 32×32: 나무 수납장 + 에스프레소 머신 + 컵"""
    im, d = canvas(32, 32)
    R(d, 0, 17, 31, 31, "3a2416"); R(d, 1, 18, 30, 30, "8a5a36"); R(d, 1, 18, 30, 19, "d9c3a5"); R(d, 0, 16, 31, 17, "efe2cf")
    R(d, 15, 20, 16, 29, "5e3c22"); P(d, 13, 24, "e9d3b0"); P(d, 18, 24, "e9d3b0")
    R(d, 2, 3, 14, 16, "2a2f3a"); R(d, 3, 4, 13, 15, "c0392b"); R(d, 3, 4, 13, 5, "e25a4a"); R(d, 11, 6, 13, 15, "8e2a20")
    R(d, 5, 8, 10, 10, "c7ced8"); R(d, 6, 11, 9, 11, "2a2f3a"); R(d, 6, 13, 9, 15, "ffffff"); R(d, 6, 13, 9, 13, "6b3b24")
    R(d, 19, 11, 22, 15, "ffffff"); R(d, 19, 11, 22, 11, "c7ced8"); R(d, 24, 12, 27, 15, "f3c945"); R(d, 24, 12, 27, 12, "c79c1b")
    R(d, 23, 8, 28, 10, "43a560"); P(d, 25, 7, "2f7d4a"); R(d, 22, 14, 23, 15, "d6efff")
    return im


def sp_vending():
    im, d = canvas(16, 32)
    R(d, 1, 1, 14, 31, "16213e"); R(d, 2, 2, 13, 30, "2e5aa8"); R(d, 2, 2, 13, 3, "8fd0ff")
    R(d, 3, 5, 10, 21, "0f1b36"); R(d, 4, 6, 9, 20, "bfe3ff")
    cols = ["e0392b", "3ddc84", "f3c945", "ffffff", "ff7a00", "5d95f3"]
    for i, y in enumerate((7, 11, 15, 19)):
        for j, x in enumerate((4, 6, 8)):
            R(d, x, y - 1, x + 1, y, cols[(i * 3 + j) % 6])
        R(d, 4, y + 1, 9, y + 1, "7aa7cc")
    R(d, 11, 6, 12, 7, "c7ced8"); P(d, 11, 10, "e0392b"); P(d, 12, 10, "3ddc84"); P(d, 11, 12, "f3c945")
    R(d, 4, 24, 11, 27, "0b1020"); R(d, 2, 29, 13, 30, "23407a")
    return im


def sp_tv():
    """TV 32×32: 나무 받침 + 화면(4..27, 4..17 — 화면 내용은 브라우저가 그림)"""
    im, d = canvas(32, 32)
    R(d, 1, 22, 30, 31, "2a1a10"); R(d, 2, 23, 29, 30, "6b4a2f"); R(d, 2, 23, 29, 23, "8f6440"); R(d, 15, 24, 16, 30, "3e2a1a")
    P(d, 12, 27, "c9a27a"); P(d, 19, 27, "c9a27a")
    R(d, 13, 19, 18, 22, "2a2d35")
    R(d, 2, 2, 29, 19, "1c1f26"); R(d, 3, 3, 28, 18, "2a2d35"); R(d, 4, 4, 27, 17, "16325c")
    P(d, 27, 18, "3ddc84")
    return im


def sp_papers():
    im, d = canvas(16, 16)
    R(d, 3, 8, 12, 13, "9aa3b0"); R(d, 4, 7, 12, 12, "ffffff"); R(d, 5, 9, 10, 9, "c7ced8"); R(d, 5, 11, 9, 11, "c7ced8")
    R(d, 2, 10, 5, 13, "f3c945")
    return im


# ───────────────────────── 사무실 배치 ─────────────────────────
# 칸 좌표(열 c, 행 r). 가구는 왼쪽 위 칸. 행 0~1 = 위쪽 벽, 열 0·23 = 옆 벽, 바닥은 1..22 × 2..15
# 2026-09-28 사용자(Pixel Agents 화면을 보여 주며) "이렇게 픽셀아트 형태로" → 참고 그림처럼 방을 벽으로 나눈다:
#   일하는 곳(열 1~14, 나무 바닥) | 벽(열 15, 문 2곳) | 회의실(열 16~22·행 2~8, 파란 카펫) / 벽(행 10) / 휴게실(행 11~15)
# 벽 조각은 32px 높이라 자기 칸 + 위 칸을 덮는다 → 벽 바로 위 칸(문 아래 끝 (15,8), 회의실 행 9)은 걷지 않는다.
DESKS = {"analyst": (1, 3), "reviewer": (4, 3), "trend": (8, 3), "lead": (11, 3), "planner": (1, 8), "scheduler": (4, 8), "money": (8, 8)}
MEET = {"lead": (19, 3, "down"), "analyst": (17, 5, "right"), "reviewer": (17, 6, "right"), "trend": (17, 7, "right"),
        "planner": (21, 5, "left"), "scheduler": (21, 6, "left"), "money": (21, 7, "left"), "boss": (19, 8, "up")}
WALL_DECOR = [("WINDOW", 1, 0), ("HANGING_PLANT", 3, 0), ("DOUBLE_BOOKSHELF", 4, 0), ("WINDOW", 6, 0), ("CLOCK", 8, 0),
              ("WINDOW", 9, 0), ("LARGE_PAINTING", 11, 0), ("WINDOW", 13, 0), ("HANGING_PLANT", 16, 0),
              ("SMALL_PAINTING_2", 17, 0), ("WHITEBOARD", 18, 0), ("SMALL_PAINTING", 20, 0), ("WINDOW", 21, 0)]
VWALL, HWALL = 15, 10                  # 세로 벽(열), 회의실·휴게실 사이 가로 벽(행, 열 16~22)
DOORS = {6, 7, 8, 13, 14, 15}          # 세로 벽의 문(행): 회의실 6~7(8은 벽 윗면에 가려짐), 휴게실 13~15
HIDDEN = {(VWALL, 8)} | {(c, HWALL - 1) for c in range(VWALL + 1, 23)}   # 벽 윗면에 가려지는 칸 → 안 지나감


def zone(c, r):
    if r < 2 or c < 1 or c > 22:
        return None
    if c <= VWALL:
        return "wood"
    return "carpet" if r < HWALL else "lounge"


def inner_walls():
    ws = {(VWALL, r) for r in range(2, 16) if r not in DOORS}
    return ws | {(c, HWALL) for c in range(VWALL + 1, 23)}


FLOOR = {"wood": (6, (25, 48, -43, -88)), "carpet": (0, (212, 34, -22, -80)), "lounge": (3, (36, 22, -2, -62))}
WALL = (214, 28, -88, -55)


def build(chars):
    S = {}                                     # 이름 → 그림
    for f in FURN:
        S[f.split("/")[-1]] = furn(f)
    S["WINDOW"] = sp_window()
    S["COOLER"] = sp_cooler()
    for i in range(3):
        S[f"PRINTER_{i}"] = sp_printer(i)
    S["CAFE"] = sp_cafe()
    S["VENDING"] = sp_vending()
    S["TV"] = sp_tv()
    S["PAPERS"] = sp_papers()
    S["CHAIR_LEAD"] = colorize(S["CUSHIONED_CHAIR_BACK"], 250, 40, -18, 10)   # 팀장 의자는 보라
    pet = img("pets/gitcat/pet.png")

    items = []   # 바닥 가구(사람과 앞뒤를 가려 그림): (그림, 열, 행, 막는 칸들, zY, 뒤집기, 이름표)

    def add(name, c, r, block=None, z=None, flip=False, tag=None, surf=False):
        im = S[name]
        w, h = im.width // T, max(1, im.height // T)
        blk = block if block is not None else [(c + i, r + j) for i in range(w) for j in range(h)]
        zy = z if z is not None else r * T + im.height
        items.append({"s": name, "c": c, "r": r, "block": blk, "z": zy, "m": flip, "tag": tag, "surf": surf})
        return items[-1]

    seats, pcs = {}, {}
    for k, (c, r) in DESKS.items():
        desk = add("DESK_FRONT", c, r, tag="desk_" + k)
        pcs[k] = len(items)
        add("PC_FRONT_OFF", c + 1, r, block=[], z=desk["z"] + 0.5, tag="pc_" + k, surf=True)
        add("CHAIR_LEAD" if k == "lead" else "CUSHIONED_CHAIR_BACK", c + 1, r + 2, z=(r + 3) * T + 1, tag="seat_" + k)
        seats[k] = {"c": c + 1, "r": r + 2, "d": "up"}
    # 책상 위 소품(성격) — 책상은 두 개씩 붙은 섬(1~6·8~13), PC 옆 칸에 놓는다
    def on_desk(name, c, who):
        add(name, c, DESKS[who][1], block=[], z=items[[i["tag"] for i in items].index("desk_" + who)]["z"] + 0.6, surf=True)
    on_desk("PAPERS", 3, "analyst"); on_desk("COFFEE", 6, "reviewer"); on_desk("COFFEE", 10, "trend")
    on_desk("POT", 11, "lead"); on_desk("COFFEE", 13, "lead")
    on_desk("PAPERS", 3, "planner"); on_desk("POT", 4, "scheduler"); on_desk("COFFEE", 6, "scheduler"); on_desk("PAPERS", 10, "money")
    # 일하는 곳 아래·옆
    printer = add("PRINTER_0", 11, 8, tag="printer")
    add("BIN", 13, 9)
    add("COOLER", 1, 12, tag="cooler")
    add("CACTUS", 1, 14, block=[(1, 15)])
    add("LARGE_PLANT", 3, 12, block=[(3, 14), (4, 14), (3, 13), (4, 13)])
    add("DOUBLE_BOOKSHELF", 6, 12, tag="shelf")
    pair = add("SMALL_TABLE_FRONT", 10, 12)
    add("CUSHIONED_CHAIR_SIDE", 9, 13, z=14 * T, tag="pairL")
    add("CUSHIONED_CHAIR_SIDE", 12, 13, z=14 * T, flip=True, tag="pairR")
    add("PAPERS", 10, 12, block=[], z=pair["z"] + 0.5, surf=True)
    add("COFFEE", 11, 13, block=[], z=pair["z"] + 0.5, surf=True)
    add("PLANT_2", 13, 11, block=[(13, 12)])
    # 회의실
    table = add("TABLE_FRONT", 18, 4)
    for w in ("analyst", "reviewer", "trend"):
        c, r, _ = MEET[w]
        add("CUSHIONED_CHAIR_SIDE", c, r, z=(r + 1) * T, tag="meet_" + w)
    for w in ("planner", "scheduler", "money"):
        c, r, _ = MEET[w]
        add("CUSHIONED_CHAIR_SIDE", c, r, z=(r + 1) * T, flip=True, tag="meet_" + w)
    add("CHAIR_LEAD", 19, 8, z=9 * T + 1, tag="meet_boss")
    add("PAPERS", 18, 5, block=[], z=table["z"] + 0.5, surf=True)
    add("COFFEE", 20, 6, block=[], z=table["z"] + 0.5, surf=True)
    add("COFFEE", 18, 7, block=[], z=table["z"] + 0.5, surf=True)
    add("PAPERS", 20, 4, block=[], z=table["z"] + 0.5, surf=True)
    add("PLANT_2", 22, 2, block=[(22, 3)])
    # 휴게실(문은 왼쪽 벽 아래 13~15행). 위: 커피 카운터·화분·TV·자판기, 13행은 가로 통로, 아래: TV를 보는 ㄷ자 소파
    add("CAFE", 16, 11, tag="cafe")
    add("PLANT", 18, 11, block=[(18, 12)])
    tv = add("TV", 19, 11, tag="tv")
    add("VENDING", 22, 11, tag="vending")
    add("SOFA_SIDE", 18, 14, z=15 * T, tag="sofaL")
    add("SOFA_BACK", 19, 14, z=15 * T + 1, tag="sofaB")
    add("SOFA_SIDE", 21, 14, z=15 * T, flip=True, tag="sofaR")

    # 칸 지도: 0 = 걸을 수 있음, 1 = 막힘
    walls = inner_walls()
    grid = [[0 if zone(c, r) and (c, r) not in walls and (c, r) not in HIDDEN else 1 for c in range(COLS)] for r in range(ROWS)]
    for it in items:
        for (c, r) in it["block"]:
            if 0 <= r < ROWS and 0 <= c < COLS:
                grid[r][c] = 1
    # 앉는 자리·들르는 곳
    sofa = [{"c": 19, "r": 14, "d": "up"}, {"c": 20, "r": 14, "d": "up"}, {"c": 18, "r": 14, "d": "right"}, {"c": 18, "r": 15, "d": "right"},
            {"c": 21, "r": 14, "d": "left"}, {"c": 21, "r": 15, "d": "left"}]
    pairs = [{"c": 9, "r": 13, "d": "right"}, {"c": 12, "r": 13, "d": "left"}]
    pois = [
        {"id": "win1", "k": "window", "c": 2, "r": 2, "d": "up"}, {"id": "win2", "k": "window", "c": 7, "r": 2, "d": "up"},
        {"id": "win3", "k": "window", "c": 10, "r": 2, "d": "up"}, {"id": "win4", "k": "window", "c": 14, "r": 2, "d": "up"},
        {"id": "win5", "k": "window", "c": 21, "r": 2, "d": "up"},
        {"id": "books", "k": "books", "c": 5, "r": 2, "d": "up"}, {"id": "shelf", "k": "books", "c": 7, "r": 14, "d": "up"},
        {"id": "board", "k": "board", "c": 18, "r": 2, "d": "up"}, {"id": "board2", "k": "board", "c": 19, "r": 2, "d": "up"},
        {"id": "printer", "k": "printer", "c": 12, "r": 10, "d": "up"},
        {"id": "cooler", "k": "water", "c": 2, "r": 13, "d": "left"},
        {"id": "cafe", "k": "coffee", "c": 16, "r": 13, "d": "up"}, {"id": "cafe2", "k": "coffee", "c": 17, "r": 13, "d": "up"},
        {"id": "vending", "k": "vending", "c": 22, "r": 13, "d": "up"},
        {"id": "plant", "k": "plant", "c": 3, "r": 11, "d": "down"}, {"id": "plant2", "k": "plant", "c": 21, "r": 3, "d": "right"},
        {"id": "clock", "k": "clock", "c": 8, "r": 2, "d": "up"},
    ]
    for p in pois:
        assert grid[p["r"]][p["c"]] == 0, f"들르는 곳이 막힌 칸: {p}"
    start = (seats["lead"]["c"], seats["lead"]["r"] + 1)
    seen, q = {start}, [start]
    for c, r in q:
        for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c + dc, r + dr)
            if 0 <= n[0] < COLS and 0 <= n[1] < ROWS and n not in seen and grid[n[1]][n[0]] == 0:
                seen.add(n); q.append(n)
    reach = lambda c, r: any((c + dc, r + dr) in seen for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1))) or (c, r) in seen
    targets = list(seats.values()) + sofa + pairs + pois + [{"c": v[0], "r": v[1]} for v in MEET.values() if v is not MEET["boss"]]
    bad = [t for t in targets if not reach(t["c"], t["r"])]
    assert not bad, f"걸어서 못 가는 자리: {bad}"
    # 자리 칸(의자)은 막힌 칸이지만 도착지로는 된다 → 화면 쪽 길찾기가 처리

    # ── 배경(바닥·벽·벽 장식) ──
    W, H = COLS * T, ROWS * T
    bg = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    tiles = {}
    for zn, (fi, col) in FLOOR.items():
        tiles[zn] = colorize(img(f"floors/floor_{fi}.png"), *col)
    for r in range(ROWS):
        for c in range(COLS):
            zn = zone(c, r)
            if zn:
                bg.alpha_composite(tiles[zn], (c * T, r * T))
    # 벽: Pixel Agents wallTiles.ts 와 같은 자동 연결(이웃 벽 N=1 E=2 S=4 W=8 → 16조각 중 하나).
    # 바깥 벽(위·양옆)은 배경에 굽고, 안쪽 벽은 가구처럼 앞뒤를 가려 그린다(벽 뒤로 지나가는 사람이 벽에 가려지게)
    wall_raw = img("walls/wall_0.png")
    wallc = colorize(wall_raw, *WALL)
    outer = lambda c, r: 0 <= c < COLS and 0 <= r < ROWS and (r == 1 or ((c == 0 or c == COLS - 1) and r >= 1))
    is_wall = lambda c, r: outer(c, r) or (c, r) in walls
    wmask = lambda c, r: (1 if is_wall(c, r - 1) else 0) | (2 if is_wall(c + 1, r) else 0) | (4 if is_wall(c, r + 1) else 0) | (8 if is_wall(c - 1, r) else 0)
    wpiece = lambda m: wallc.crop(((m % 4) * 16, (m // 4) * 32, (m % 4) * 16 + 16, (m // 4) * 32 + 32))
    for r in range(ROWS):
        for c in range(COLS):
            if outer(c, r):
                bg.alpha_composite(wpiece(wmask(c, r)), (c * T, r * T - 16) if r * T - 16 >= 0 else (c * T, 0))
    wall_items = []
    for (c, r) in sorted(walls, key=lambda p: (p[1], p[0])):
        m = wmask(c, r)
        S[f"WALL_{m}"] = wpiece(m)
        wall_items.append({"s": f"WALL_{m}", "x": c * T, "y": r * T - 16, "z": (r + 1) * T})
    # 휴게실 벽에 거는 액자(벽 조각과 같은 자리에 겹쳐 그림)
    wall_items.append({"s": "SMALL_PAINTING", "x": 18 * T, "y": HWALL * T - 16, "z": (HWALL + 1) * T + 0.2})
    wall_items.append({"s": "SMALL_PAINTING_2", "x": 21 * T, "y": HWALL * T - 16, "z": (HWALL + 1) * T + 0.2})
    glass, clock, board = [], None, None
    for name, c, r in WALL_DECOR:
        im = S[name]
        bg.alpha_composite(im, (c * T, r * T))
        if name == "WINDOW":
            glass.append([c * T + 4, 12, 24, 14])
        if name == "CLOCK":
            clock = [c * T + 8, 16]
        if name == "WHITEBOARD":
            board = [c * T + 4, 10, 24, 12]
    pxb = bg.load()
    for gx, gy, gw, gh in glass:
        for y in range(gy, gy + gh):
            for x in range(gx, gx + gw):
                if pxb[x, y][:3] != hx("dfe6ee") and pxb[x, y][:3] != hx("aab6c6"):
                    pxb[x, y] = (0, 0, 0, 0)
    # 바닥 가장자리 그림자(벽 아래 1줄): 위쪽 벽 밑, 휴게실 벽 밑
    def shade(x, y, k=.7):
        r0, g0, b0, a0 = pxb[x, y]
        pxb[x, y] = (int(r0 * k), int(g0 * k), int(b0 * k), a0)
    for x in range(T, (COLS - 1) * T):
        shade(x, 2 * T)
    for x in range((VWALL + 1) * T, (COLS - 1) * T):
        shade(x, (HWALL + 1) * T)
    for r in range(2, ROWS):   # 세로 벽 오른쪽 바닥에 옅은 그림자
        if (VWALL, r) in walls or (VWALL, r + 1) in walls:
            for y in range(r * T, r * T + T):
                shade((VWALL + 1) * T, y, .8)

    # ── 묶음 그림(아틀라스) ──
    sheet = [(f"char_{k}", chars[k]) for k in ORDER] + [("cat", pet)]
    names = sorted({it["s"] for it in items} | {it["s"] for it in wall_items}
                   | {"PRINTER_1", "PRINTER_2", "PC_FRONT_ON_1", "PC_FRONT_ON_2", "PC_FRONT_ON_3", "PC_BACK"})
    sheet += [(n, S[n]) for n in names]
    AW = 512
    x = y = rowh = 0
    rects, placed = {}, []
    for n, im in sheet:
        if x + im.width > AW:
            x, y, rowh = 0, y + rowh + 1, 0
        rects[n] = [x, y, im.width, im.height]
        placed.append((n, im, x, y))
        x += im.width + 1
        rowh = max(rowh, im.height)
    atlas = Image.new("RGBA", (AW, y + rowh), (0, 0, 0, 0))
    for n, im, x0, y0 in placed:
        atlas.alpha_composite(im, (x0, y0))

    furn_out = [{"s": it["s"], "x": it["c"] * T, "y": it["r"] * T, "z": it["z"], **({"m": 1} if it["m"] else {}), **({"tag": it["tag"]} if it["tag"] else {})}
                for it in items] + wall_items   # 벽은 맨 뒤에 붙인다(pcs·printer 번호가 그대로)
    tv_i = [i for i, it in enumerate(items) if it["tag"] == "tv"][0]
    meta = {
        "tile": T, "cols": COLS, "rows": ROWS, "w": W, "h": H, "aw": atlas.width, "ah": atlas.height,
        "sprites": rects, "furniture": furn_out,
        "grid": ["".join(str(v) for v in row) for row in grid],
        "seats": seats, "meet": {k: {"c": v[0], "r": v[1], "d": v[2]} for k, v in MEET.items()},
        "sofa": sofa, "pairs": pairs, "pois": pois,
        "pcs": {k: pcs[k] for k in pcs}, "printer": [i for i, it in enumerate(items) if it["tag"] == "printer"][0],
        "glass": glass, "clock": clock, "board": board,
        "tv": [items[tv_i]["c"] * T + 4, items[tv_i]["r"] * T + 4, 24, 14],
        "char": {"w": 16, "h": 32, "frames": 7, "sit": 6},
        "cat": {"start": [8, 6]},
        "credit": "그림: Pixel Agents(MIT) · Metro City 캐릭터(CC0)",
    }
    return bg, atlas, meta, chars


def faces(chars):
    for k, im in chars.items():
        fr = im.crop((16, 0, 32, 32))                     # 앞모습 서 있는 칸
        head = fr.crop((0, 2, 16, 18))
        big = head.resize((96, 96), Image.NEAREST)
        big.save(OUT / f"face_{k}.png", optimize=True)


def preview(bg, atlas, meta, path):
    """확인용: 모두 자리에 앉혀서 3배로"""
    S = meta["sprites"]
    im = Image.new("RGBA", (meta["w"], meta["h"]), (27, 29, 38, 255))
    d = ImageDraw.Draw(im)
    for gx, gy, gw, gh in meta["glass"]:
        d.rectangle((gx, gy, gx + gw - 1, gy + gh - 1), fill=(142, 197, 240, 255))
    im.alpha_composite(bg)
    draws = []
    for f in meta["furniture"]:
        x, y, w, h = S[f["s"]]
        spr = atlas.crop((x, y, x + w, y + h))
        if f.get("m"):
            spr = spr.transpose(Image.FLIP_LEFT_RIGHT)
        draws.append((f["z"], spr, f["x"], f["y"]))
    who = list(meta["seats"].items())
    sit = meta["char"]["sit"]
    for i, (k, s) in enumerate(who):
        x, y, w, h = S["char_" + k]
        fr = atlas.crop((x + 3 * 16, y + 32, x + 4 * 16, y + 64))   # 위를 보고 타이핑
        cx, cy = s["c"] * 16 + 8, s["r"] * 16 + 8
        draws.append((cy + 8.5, fr, cx - 8, cy + sit - 32))
    # 걷는 모습 몇 명(앞·옆)
    for j, (k, c, r, row, col) in enumerate([("trend", 17, 14, 0, 1), ("money", 15, 7, 2, 0), ("reviewer", 7, 7, 0, 2)]):
        x, y, w, h = S["char_" + k]
        fr = atlas.crop((x + col * 16, y + row * 32, x + col * 16 + 16, y + row * 32 + 32))
        draws.append((r * 16 + 16.5, fr, c * 16, r * 16 + 8 - 32))
    draws.sort(key=lambda t: t[0])
    for _, spr, x, y in draws:
        im.alpha_composite(spr, (int(x), int(y)))
    im = im.resize((im.width * 3, im.height * 3), Image.NEAREST)
    im.convert("RGB").save(path)


def main():
    ensure_src()
    OUT.mkdir(exist_ok=True)
    chars = make_chars()
    bg, atlas, meta, chars = build(chars)
    bg.save(OUT / "office_bg.png", optimize=True)
    atlas.save(OUT / "office.png", optimize=True)
    (OUT / "office.json").write_text(json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    faces(chars)
    lic = (SRC / "LICENSE").read_text(encoding="utf-8")
    (OUT / "LICENSE-office-art.txt").write_text(
        "사무실 그림(office.png·office_bg.png·face_*.png)은 아래 그림을 바탕으로 색을 바꾸고 소품을 더해 만들었습니다.\n"
        "- Pixel Agents 그림(가구·바닥·벽·캐릭터·고양이) — https://github.com/pixel-agents-hq/pixel-agents (MIT, 아래 문구)\n"
        "- 캐릭터 바탕: JIK-A-4 \"Metro City\" — https://jik-a-4.itch.io/metrocity-free-topdown-character-pack (CC0)\n"
        "- 창문·정수기·복합기·커피 카운터·자판기·TV·서류: 채널대시보드/직원그림/make_office.py 가 직접 그림\n\n" + lic, encoding="utf-8")
    print("atlas", atlas.size, "bg", bg.size, "가구", len(meta["furniture"]), "들르는 곳", len(meta["pois"]))
    if "--preview" in sys.argv:
        p = sys.argv[sys.argv.index("--preview") + 1]
        preview(bg, atlas, meta, p)
        print("미리보기", p)


if __name__ == "__main__":
    main()
