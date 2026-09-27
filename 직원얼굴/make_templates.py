# 마케팅팀 직원 얼굴·움직임 만들기(2026-09-27, 이 맥에서 무료). 무거운 것(가상환경 venv·모델·LivePortrait·결과)은 ~/.cache/dashboard-staff 에 있고,
# 이 폴더는 그 스크립트의 보관본이다. 다시 만들 때: cp 직원얼굴/*.py ~/.cache/dashboard-staff/ && cd ~/.cache/dashboard-staff 뒤
#   ./venv/bin/python dl.py sdxl · dl.py lp · make_templates.py(처음 한 번) → gen_faces.py(후보) → make_staff_media.py 의 PICK 고치기
#   → make_staff_media.py prep → PYTORCH_ENABLE_MPS_FALLBACK=1 ./venv/bin/python animate_batch.py src/lead.png,… → make_staff_media.py encode "<대시보드>/staff"  (얼굴 찾기는 YuNet — InsightFace 모델은 비상업 전용이라 안 씀)
# 움직임 템플릿 3개(LivePortrait 예제에서 잘라 만든다): talk(말하기) · idle(듣기: 눈 깜빡임·고개 조금, 입은 가만히) · laugh(웃음 반응)
import pickle
from pathlib import Path
import numpy as np

EX = Path(__file__).parent / "LivePortrait/assets/examples/driving"
OUT = Path(__file__).parent / "tpl"
OUT.mkdir(exist_ok=True)
LIP = [6, 12, 14, 17, 19, 20]


def load(n):
    d = pickle.load(open(EX / f"{n}.pkl", "rb"))
    if "c_d_eyes_lst" not in d and "c_eyes_lst" not in d:
        d["c_d_eyes_lst"] = [np.array([[0.38, 0.38]], np.float32)] * d["n_frames"]
        d["c_d_lip_lst"] = [np.array([[0.0]], np.float32)] * d["n_frames"]
    return d


def cut(d, a, b):
    k = {"c_eyes_lst": "c_d_eyes_lst", "c_lip_lst": "c_d_lip_lst"}
    out = {"n_frames": b - a, "output_fps": d.get("output_fps", 25), "motion": d["motion"][a:b]}
    for key in ("c_d_eyes_lst", "c_d_lip_lst", "c_eyes_lst", "c_lip_lst"):
        if key in d:
            out[k.get(key, key)] = d[key][a:b]
    return out


talk = cut(load("d8"), 0, 90)            # 실제 말하는 영상에서 온 움직임(30fps, 3초) — 뒤집어 붙여 6초 반복
idle = cut(load("d7"), 0, 120)           # 눈 깜빡임이 많은 4초
m0 = np.asarray(idle["motion"][0]["exp"]).copy()
for f in idle["motion"]:                 # 듣는 사람: 입은 첫 프레임 그대로
    e = np.asarray(f["exp"]).copy().reshape(1, 21, 3)
    e[0, LIP, :] = m0.reshape(1, 21, 3)[0, LIP, :]
    f["exp"] = e.astype(np.float32)
laugh = load("laugh")
for n, d in (("talk", talk), ("idle", idle), ("laugh", laugh)):
    pickle.dump(d, open(OUT / f"{n}.pkl", "wb"))
    print(n, d["n_frames"], "frames @", d.get("output_fps"))
