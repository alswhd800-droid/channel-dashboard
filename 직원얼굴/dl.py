# 마케팅팀 직원 얼굴·움직임 만들기(2026-09-27, 이 맥에서 무료). 무거운 것(가상환경 venv·모델·LivePortrait·결과)은 ~/.cache/dashboard-staff 에 있고,
# 이 폴더는 그 스크립트의 보관본이다. 다시 만들 때: cp 직원얼굴/*.py ~/.cache/dashboard-staff/ && cd ~/.cache/dashboard-staff 뒤
#   ./venv/bin/python dl.py sdxl · dl.py lp · make_templates.py(처음 한 번) → gen_faces.py(후보) → make_staff_media.py 의 PICK 고치기
#   → make_staff_media.py prep → PYTORCH_ENABLE_MPS_FALLBACK=1 ./venv/bin/python animate_batch.py src/lead.png,… → make_staff_media.py encode "<대시보드>/staff"  (얼굴 찾기는 YuNet — InsightFace 모델은 비상업 전용이라 안 씀)
# 모델 받기(한 번만): 얼굴 사진 RealVisXL V5.0(openrail++, fp16 diffusers 파일만 약 7GB) + LivePortrait 사람용 가중치(MIT)
import sys
from huggingface_hub import snapshot_download
which = sys.argv[1]
if which == "sdxl":
    p = snapshot_download("SG161222/RealVisXL_V5.0", allow_patterns=["model_index.json", "scheduler/*", "tokenizer/*", "tokenizer_2/*",
        "text_encoder/config.json", "text_encoder/model.fp16.safetensors", "text_encoder_2/config.json", "text_encoder_2/model.fp16.safetensors",
        "unet/config.json", "unet/diffusion_pytorch_model.fp16.safetensors", "vae/config.json", "vae/diffusion_pytorch_model.fp16.safetensors"])
else:
    p = snapshot_download("KwaiVGI/LivePortrait", local_dir="LivePortrait/pretrained_weights",
        allow_patterns=["liveportrait/*"])
print("done", p)
