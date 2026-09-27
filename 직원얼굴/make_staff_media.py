# 마케팅팀 직원 얼굴·움직임 만들기(2026-09-27, 이 맥에서 무료). 무거운 것(가상환경 venv·모델·LivePortrait·결과)은 ~/.cache/dashboard-staff 에 있고,
# 이 폴더는 그 스크립트의 보관본이다. 다시 만들 때: cp 직원얼굴/*.py ~/.cache/dashboard-staff/ && cd ~/.cache/dashboard-staff 뒤
#   ./venv/bin/python dl.py sdxl · dl.py lp · make_templates.py(처음 한 번) → gen_faces.py(후보) → make_staff_media.py 의 PICK 고치기
#   → make_staff_media.py prep → PYTORCH_ENABLE_MPS_FALLBACK=1 ./venv/bin/python animate_batch.py src/lead.png,… → make_staff_media.py encode "<대시보드>/staff"  (얼굴 찾기는 YuNet — InsightFace 모델은 비상업 전용이라 안 씀)
# 고른 얼굴 → 대시보드 파일(staff/). 두 단계:
#   python make_staff_media.py prep     → src/<키>.png(512px, 움직임 만들 원본) · box.json(작은 칸용 얼굴 둘레)
#   (python animate_batch.py src/lead.png,… → anim/<키>_talk|idle|laugh.mp4)
#   python make_staff_media.py encode 대시보드/staff  → <키>.jpg(큰 화면 정지) <키>.webp(작은 얼굴) <키>_talk.mp4(512) <키>_idle.mp4·<키>_laugh.mp4(240, 얼굴 둘레)
import json, subprocess, sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
PICK = {"lead": 22, "analyst": 44, "reviewer": 22, "trend": 44, "planner": 22, "scheduler": 44, "money": 44}
SRC, ANIM = HERE / "src", HERE / "anim"
SRC.mkdir(exist_ok=True)
S = 512


def prep():
    det = cv2.FaceDetectorYN.create(str(HERE / "yunet.onnx"), "", (S, S), 0.5, 0.3, 50)
    box = {}
    for k, seed in PICK.items():
        im = Image.open(HERE / f"cand/{k}_{seed}.png").convert("RGB").resize((S, S), Image.LANCZOS)
        im.save(SRC / f"{k}.png")
        _, f = det.detect(cv2.cvtColor(np.array(im), cv2.COLOR_RGB2BGR))
        x, y, w, h = f[np.argmax(f[:, 2] * f[:, 3])][:4]
        side = min(S, int(max(w, h) * 1.75) // 2 * 2)
        cx, cy = x + w / 2, y + h / 2 + h * 0.08
        x0 = int(min(max(0, cx - side / 2), S - side)) // 2 * 2
        y0 = int(min(max(0, cy - side / 2), S - side)) // 2 * 2
        box[k] = [x0, y0, side]
        print(k, "얼굴", int(w), "x", int(h), "→ 작은 칸", box[k])
    (HERE / "box.json").write_text(json.dumps(box))


def ff(*a):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *a], check=True)


def encode(dst):
    dst = Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    box = json.loads((HERE / "box.json").read_text())
    enc = ["-an", "-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-preset", "slow"]
    pingpong = "split[a][b];[b]reverse,trim=start_frame=1,setpts=PTS-STARTPTS[r];[a][r]concat=n=2:v=1"
    for k in PICK:
        x0, y0, side = box[k]
        im = Image.open(SRC / f"{k}.png").convert("RGB")
        im.save(dst / f"{k}.jpg", quality=82, optimize=True, progressive=True)
        im.crop((x0, y0, x0 + side, y0 + side)).resize((256, 256), Image.LANCZOS).save(dst / f"{k}.webp", "WEBP", quality=82, method=6)
        ff("-i", str(ANIM / f"{k}_talk.mp4"), "-filter_complex", f"[0:v]{pingpong},scale={S}:{S}[o]", "-map", "[o]", *enc, "-crf", "24", str(dst / f"{k}_talk.mp4"))
        for n in ("idle", "laugh"):
            ff("-i", str(ANIM / f"{k}_{n}.mp4"), "-filter_complex", f"[0:v]crop={side}:{side}:{x0}:{y0},{pingpong},scale=240:240[o]", "-map", "[o]",
               *enc, "-crf", "29", str(dst / f"{k}_{n}.mp4"))
        sz = {f.name: f.stat().st_size // 1024 for f in dst.glob(f"{k}*")}
        print(k, sz, flush=True)


if __name__ == "__main__":
    prep() if sys.argv[1] == "prep" else encode(sys.argv[2])
