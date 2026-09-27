#!/usr/bin/env python3
"""마케팅팀 직원 얼굴 사진(2026-09-27 사용자: "회의실은 진짜 사람이 나와서 회의하는 느낌 들게").
화상회의 웹캠 화면처럼 보이는 실사 사진 7장. 실제 인물이 아닌 가상의 직원이다.
  python3 직원사진_만들기.py                 # 없는 사람만 만든다
  python3 직원사진_만들기.py analyst trend   # 이 사람만 다시 만든다(얼굴을 바꾸고 싶을 때)
  --openai : gpt-image-2 medium(1장 약 $0.063)로 만든다. 기본은 Gemini gemini-2.5-flash-image(1장 약 $0.039)
             (2026-09-27 기준 OpenAI 키는 크레딧이 없어 Gemini가 기본)
원본(1024px PNG)은 staff/_원본/ (깃에 안 올림), 대시보드가 쓰는 건 staff/<키>.webp (256px, 한 장 10~20KB).
열쇠는 환경변수 → 없으면 옆 채널 폴더 .env 에서 읽는다(화면에 찍지 않음)."""
import base64, json, os, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
OUT, RAW = ROOT / "staff", ROOT / "staff" / "_원본"
SIZE, QUALITY = 256, 80
GEMINI_MODEL = "gemini-2.5-flash-image"

STYLE = ("Photorealistic still frame from a laptop webcam during a friendly team video meeting. {who} "
         "Head and shoulders, centered, eye level, looking straight into the camera with {expr}. "
         "Behind: {bg}, softly out of focus. Soft natural daylight, realistic skin texture, natural colors, "
         "subtle webcam sharpness. Square framing with a little space above the head. "
         "An ordinary everyday person, not a celebrity. No text, no logos, no watermark, no on-screen interface.")
PEOPLE = {   # collect.py STAFF 와 같은 키
    "lead": ("A Korean man in his early 40s who leads a YouTube marketing team: short neat black hair, clean-shaven, "
             "a navy blazer over a plain white shirt, no tie.", "a calm, confident slight smile",
             "a bright modern office with a glass-walled meeting room"),
    "analyst": ("A Korean woman in her early 30s who works as a data analyst: straight black hair just past the shoulders, "
                "thin silver-rimmed glasses, a beige knit cardigan over a white top.", "an attentive, composed expression and a faint smile",
                "a desk with two monitors showing colorful line and bar charts"),
    "reviewer": ("A Korean man in his early 30s who reviews video performance: slightly messy medium-length dark-brown hair, "
                 "a black crew-neck t-shirt, over-ear headphones resting around his neck.", "a focused, frank half-smile",
                 "a dim video-editing room lit by a monitor showing an editing timeline"),
    "trend": ("A Korean woman in her late 20s who researches online trends: long wavy dark-brown hair, small gold hoop earrings, "
              "a bright orange knit top.", "an energetic, cheerful open smile",
              "a bright, colorful co-working space with green plants and a small warm neon light"),
    "planner": ("A Korean man in his late 20s who plans YouTube content: soft permed black hair, round tortoiseshell glasses, "
                "an olive-green crew-neck sweater.", "a friendly, thoughtful smile",
                "a whiteboard covered with colorful sticky notes"),
    "scheduler": ("A Korean man in his mid 30s who manages the upload schedule: short side-parted black hair, "
                  "a light-blue oxford button-down shirt.", "a polite, composed smile",
                  "a tidy office wall with a large monthly wall calendar and a round wall clock"),
    "money": ("A Korean woman in her mid 30s who manages revenue and costs: black hair tied in a neat low ponytail, "
              "a white blouse under a charcoal-gray blazer.", "a warm, professional smile",
              "a neat office with bookshelves and binders"),
}


def env_key(name):
    if os.environ.get(name):
        return os.environ[name]
    for ch in ("거대한비밀", "시술백과", "필요한법", "거인의무덤", "이유상자", "돈구"):
        f = ROOT.parent / ch / ".env"
        if f.exists():
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith(name + "="):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
    sys.exit(f"{name} 를 찾지 못했어요")


def call(req):
    for attempt in range(3):
        try:
            return json.load(urllib.request.urlopen(req, timeout=600)), None
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503) and attempt < 2 and "quota" not in msg and "credit" not in msg:
                time.sleep(10 * (attempt + 1))
                continue
            return None, f"실패 {e.code} {msg}"
        except Exception as e:
            if attempt < 2:
                time.sleep(10)
                continue
            return None, f"실패 {type(e).__name__} {e}"


def png_openai(prompt, token):
    body = json.dumps({"model": "gpt-image-2", "prompt": prompt, "size": "1024x1024", "quality": "medium", "n": 1}).encode()
    d, err = call(urllib.request.Request("https://api.openai.com/v1/images/generations", data=body,
                                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}))
    return (base64.b64decode(d["data"][0]["b64_json"]), None) if d else (None, err)


def png_gemini(prompt, token):
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "1:1"}}}).encode()
    d, err = call(urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent", data=body,
                                         headers={"x-goog-api-key": token, "Content-Type": "application/json"}))
    if not d:
        return None, err
    for p in ((d.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []:
        if (p.get("inlineData") or {}).get("data"):
            return base64.b64decode(p["inlineData"]["data"]), None
    return None, "그림이 안 왔어요: " + json.dumps(d, ensure_ascii=False)[:300]


def make(key, engine, token):
    who, expr, bg = PEOPLE[key]
    data, err = engine(STYLE.format(who=who, expr=expr, bg=bg), token)
    if err:
        return f"{key}: {err}"
    raw = RAW / f"{key}.png"
    raw.write_bytes(data)
    im = Image.open(raw).convert("RGB")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))   # 정사각형이 아니면 가운데만
    im.resize((SIZE, SIZE), Image.LANCZOS).save(OUT / f"{key}.webp", "WEBP", quality=QUALITY, method=6)
    return f"{key}: 완료 {w}x{h} → {(OUT / f'{key}.webp').stat().st_size // 1024}KB"


if __name__ == "__main__":
    args = sys.argv[1:]
    use_openai = "--openai" in args
    want = [a for a in args if a in PEOPLE]
    bad = [a for a in args if a not in PEOPLE and not a.startswith("--")]
    if bad:
        sys.exit(f"모르는 키: {bad} (쓸 수 있는 키: {', '.join(PEOPLE)})")
    OUT.mkdir(exist_ok=True)
    RAW.mkdir(exist_ok=True)
    todo = want or [k for k in PEOPLE if not (OUT / f"{k}.webp").exists()]
    if not todo:
        sys.exit("모두 있어요. 다시 만들려면 키를 적어 주세요 (예: python3 직원사진_만들기.py analyst)")
    engine, token, price, label = ((png_openai, env_key("OPENAI_API_KEY"), 0.063, "gpt-image-2 medium") if use_openai
                                   else (png_gemini, env_key("GEMINI_API_KEY"), 0.039, GEMINI_MODEL))
    print(f"{len(todo)}장 만드는 중 ({label}, 약 ${price * len(todo):.2f})…", flush=True)
    with ThreadPoolExecutor(max_workers=len(todo)) as ex:   # 서로 독립이라 한꺼번에
        for line in ex.map(lambda k: make(k, engine, token), todo):
            print(line, flush=True)
