# 마케팅팀 직원 얼굴·움직임 만들기(2026-09-27, 이 맥에서 무료). 무거운 것(가상환경 venv·모델·LivePortrait·결과)은 ~/.cache/dashboard-staff 에 있고,
# 이 폴더는 그 스크립트의 보관본이다. 다시 만들 때: cp 직원얼굴/*.py ~/.cache/dashboard-staff/ && cd ~/.cache/dashboard-staff 뒤
#   ./venv/bin/python dl.py sdxl · dl.py lp · make_templates.py(처음 한 번) → gen_faces.py(후보) → make_staff_media.py 의 PICK 고치기
#   → make_staff_media.py prep → PYTORCH_ENABLE_MPS_FALLBACK=1 ./venv/bin/python animate_batch.py src/lead.png,… → make_staff_media.py encode "<대시보드>/staff"  (얼굴 찾기는 YuNet — InsightFace 모델은 비상업 전용이라 안 씀)
# 직원 사진 → 움직이는 화상회의 영상(LivePortrait, MIT). 얼굴 찾기는 InsightFace(비상업 전용 모델) 대신 OpenCV YuNet(MIT)으로 바꿔 쓴다.
#   python animate.py 사진.png 템플릿.pkl 출력.mp4 [--region all|pose|exp|lip|eyes] [--mult 1.0]
import sys, types
from pathlib import Path
import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
LP = HERE / "LivePortrait"
sys.path.insert(0, str(LP))

import src.utils.cropper as cropper_mod   # noqa: E402


class _Face:
    def __init__(self, bbox, pts):
        self.bbox, self.landmark_2d_106, self.kps = bbox, pts, pts


class YuNetFace:
    """FaceAnalysisDIY 자리: get() 이 얼굴(큰 것부터)을 돌려준다. 점 5개(두 눈·코·입꼬리 둘)는 LivePortrait crop 이 그대로 받는다."""
    def __init__(self, *a, **k):
        self.det = None

    def prepare(self, *a, **k):
        pass

    def warmup(self):
        pass

    def get(self, img_bgr, **kw):
        h, w = img_bgr.shape[:2]
        det = cv2.FaceDetectorYN.create(str(HERE / "yunet.onnx"), "", (w, h), 0.6, 0.3, 50)
        _, faces = det.detect(img_bgr)
        out = []
        for f in (faces if faces is not None else []):
            x, y, bw, bh = f[:4]
            pts = f[4:14].reshape(5, 2).astype(np.float32)   # 오른눈·왼눈·코·오른입꼬리·왼입꼬리
            out.append(_Face(np.array([x, y, x + bw, y + bh], np.float32), pts))
        out.sort(key=lambda o: -(o.bbox[2] - o.bbox[0]) * (o.bbox[3] - o.bbox[1]))
        return out[: kw.get("max_face_num", 0) or None]


cropper_mod.FaceAnalysisDIY = YuNetFace

from src.config.argument_config import ArgumentConfig   # noqa: E402
from src.config.inference_config import InferenceConfig   # noqa: E402
from src.config.crop_config import CropConfig   # noqa: E402
from src.live_portrait_pipeline import LivePortraitPipeline   # noqa: E402


def fields(cls, d):
    return cls(**{k: v for k, v in d.items() if hasattr(cls, k)})


if __name__ == "__main__":
    a = sys.argv[1:]
    src, drv, out = a[0], a[1], Path(a[2])
    import pickle, tempfile
    d = pickle.load(open(drv, "rb"))
    if "c_d_eyes_lst" not in d and "c_eyes_lst" not in d:   # 새 템플릿엔 눈·입 비율이 없다 — 되맞춤(retargeting)을 안 쓰면 쓰이지 않는 값이라 중립값을 채운다
        n = d["n_frames"]
        d["c_d_eyes_lst"] = [np.array([[0.38, 0.38]], np.float32)] * n
        d["c_d_lip_lst"] = [np.array([[0.0]], np.float32)] * n
        f = tempfile.NamedTemporaryFile(suffix=".pkl", delete=False)
        pickle.dump(d, f); f.close()
        drv = f.name
    opt = lambda k, dv: a[a.index(k) + 1] if k in a else dv
    args = ArgumentConfig(source=src, driving=drv, output_dir=str(out.parent), flag_pasteback=True, flag_do_crop=True, flag_stitching=True,
                          flag_relative_motion=True, animation_region=opt("--region", "all"), driving_multiplier=float(opt("--mult", "1.0")),
                          flag_use_half_precision=False, source_max_dim=int(opt("--dim", "768")))
    inf, crop = fields(InferenceConfig, args.__dict__), fields(CropConfig, args.__dict__)
    inf.flag_use_half_precision = False
    pipe = LivePortraitPipeline(inference_cfg=inf, crop_cfg=crop)
    wfp, _ = pipe.execute(args)
    Path(wfp).rename(out)
    print("OK", out)
