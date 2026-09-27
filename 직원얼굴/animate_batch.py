# 마케팅팀 직원 얼굴·움직임 만들기(2026-09-27, 이 맥에서 무료). 무거운 것(가상환경 venv·모델·LivePortrait·결과)은 ~/.cache/dashboard-staff 에 있고,
# 이 폴더는 그 스크립트의 보관본이다. 다시 만들 때: cp 직원얼굴/*.py ~/.cache/dashboard-staff/ && cd ~/.cache/dashboard-staff 뒤
#   ./venv/bin/python dl.py sdxl · dl.py lp · make_templates.py(처음 한 번) → gen_faces.py(후보) → make_staff_media.py 의 PICK 고치기
#   → make_staff_media.py prep → PYTORCH_ENABLE_MPS_FALLBACK=1 ./venv/bin/python animate_batch.py src/lead.png,… → make_staff_media.py encode "<대시보드>/staff"  (얼굴 찾기는 YuNet — InsightFace 모델은 비상업 전용이라 안 씀)
# 여러 사진 × 템플릿을 한 번에(모델은 한 번만 올린다): python animate_batch.py 사진1.png[,사진2…] → anim/<키>_<talk|idle|laugh>.mp4
import sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import animate  # noqa: E402  (YuNet 얼굴 찾기로 바꿔 끼운 LivePortrait)
from animate import ArgumentConfig, InferenceConfig, CropConfig, LivePortraitPipeline, fields  # noqa: E402

srcs = [Path(p) for p in sys.argv[1].split(",")]
tpls = sys.argv[2].split(",") if len(sys.argv) > 2 else ["talk", "idle", "laugh"]
out = HERE / "anim"
out.mkdir(exist_ok=True)
base = ArgumentConfig(source=str(srcs[0]), driving=str(HERE / "tpl/talk.pkl"), output_dir=str(out), flag_pasteback=True, flag_do_crop=True,
                      flag_stitching=True, flag_relative_motion=True, animation_region="all", flag_use_half_precision=False, source_max_dim=512)
inf, crop = fields(InferenceConfig, base.__dict__), fields(CropConfig, base.__dict__)
inf.flag_use_half_precision = False
pipe = LivePortraitPipeline(inference_cfg=inf, crop_cfg=crop)
for s in srcs:
    key = s.stem.split("_")[0]
    for t in tpls:
        t0 = time.time()
        args = ArgumentConfig(**{**base.__dict__, "source": str(s), "driving": str(HERE / f"tpl/{t}.pkl")})
        wfp, wfp_concat = pipe.execute(args)
        Path(wfp).rename(out / f"{key}_{t}.mp4")
        Path(wfp_concat).unlink(missing_ok=True)
        print(f"{key}_{t} {time.time() - t0:.0f}초", flush=True)
