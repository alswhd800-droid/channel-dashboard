# 마케팅팀 직원 얼굴·움직임 만들기(2026-09-27, 이 맥에서 무료). 무거운 것(가상환경 venv·모델·LivePortrait·결과)은 ~/.cache/dashboard-staff 에 있고,
# 이 폴더는 그 스크립트의 보관본이다. 다시 만들 때: cp 직원얼굴/*.py ~/.cache/dashboard-staff/ && cd ~/.cache/dashboard-staff 뒤
#   ./venv/bin/python dl.py sdxl · dl.py lp · make_templates.py(처음 한 번) → gen_faces.py(후보) → make_staff_media.py 의 PICK 고치기
#   → make_staff_media.py prep → PYTORCH_ENABLE_MPS_FALLBACK=1 ./venv/bin/python animate_batch.py src/lead.png,… → make_staff_media.py encode "<대시보드>/staff"  (얼굴 찾기는 YuNet — InsightFace 모델은 비상업 전용이라 안 씀)
# 대시보드 마케팅팀 직원 얼굴 후보(가상의 인물) — 이 맥에서 RealVisXL V5.0(openrail++)으로 무료 생성
#   python gen_faces.py [키 …] [--seeds 11,22,33]   → cand/<키>_<씨앗>.png (1024px)
import sys, time
from pathlib import Path
import torch
from diffusers import StableDiffusionXLPipeline, DPMSolverMultistepScheduler

OUT = Path(__file__).parent / "cand"
OUT.mkdir(exist_ok=True)
STYLE = ("photo, still frame from a laptop webcam during a video call, head and shoulders portrait of {who}, "
         "centered, eye level, looking directly at the camera, {expr}, mouth closed, {bg} in the background, softly out of focus, "
         "soft natural window light, realistic skin texture with pores, natural colors, candid, sharp focus on the face")
NEG = ("cartoon, anime, illustration, painting, drawing, 3d render, cgi, doll, plastic skin, airbrushed, beauty filter, heavy makeup, "
       "deformed, disfigured, asymmetric eyes, cross-eyed, open mouth, teeth, hands, fingers, extra limbs, text, watermark, logo, "
       "frame, border, lowres, blurry face, jpeg artifacts, oversaturated, tilted head, profile view")
PEOPLE = {
    "lead": ("a 42-year-old Korean man, short neat black hair, clean-shaven, navy blazer over a plain white shirt",
             "calm confident slight smile", "a bright modern office with glass walls"),
    "analyst": ("a 31-year-old Korean woman, straight black shoulder-length hair, thin silver-rimmed glasses, beige knit cardigan over a white top",
                "attentive composed expression with a faint smile", "a desk with two monitors showing line charts"),
    "reviewer": ("a 32-year-old Korean man, slightly messy medium-length dark brown hair, black crew-neck t-shirt, over-ear headphones around his neck",
                 "focused frank half smile", "a dim video editing room lit by computer monitors"),
    "trend": ("a 28-year-old Korean woman, long wavy dark brown hair, small gold hoop earrings, bright orange knit sweater",
              "cheerful friendly smile", "a bright colorful co-working space with green plants"),
    "planner": ("a 29-year-old Korean man, soft permed black hair, round tortoiseshell glasses, olive green crew-neck sweater",
                "friendly thoughtful smile", "a whiteboard covered with colorful sticky notes"),
    "scheduler": ("a 35-year-old Korean man, short side-parted black hair, light blue oxford button-down shirt",
                  "polite composed smile", "an office wall with a large monthly wall calendar and a round wall clock"),
    "money": ("a 36-year-old Korean woman, black hair tied in a neat low ponytail, white blouse under a charcoal gray blazer",
              "warm professional smile", "a tidy office with bookshelves and binders"),
}

args = sys.argv[1:]
seeds = [11, 22, 33]
if "--seeds" in args:
    seeds = [int(x) for x in args[args.index("--seeds") + 1].split(",")]
    args = [a for i, a in enumerate(args) if a != "--seeds" and (i == 0 or args[i - 1] != "--seeds")]
keys = [a for a in args if a in PEOPLE] or list(PEOPLE)

t0 = time.time()
pipe = StableDiffusionXLPipeline.from_pretrained("SG161222/RealVisXL_V5.0", torch_dtype=torch.float16, variant="fp16", use_safetensors=True)
pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, use_karras_sigmas=True, algorithm_type="dpmsolver++")
pipe.to("mps")
print(f"모델 준비 {time.time() - t0:.0f}초", flush=True)
for k in keys:
    who, expr, bg = PEOPLE[k]
    for s in seeds:
        t = time.time()
        img = pipe(STYLE.format(who=who, expr=expr, bg=bg), negative_prompt=NEG, num_inference_steps=28, guidance_scale=5.0,
                   width=1024, height=1024, generator=torch.Generator("cpu").manual_seed(s)).images[0]
        img.save(OUT / f"{k}_{s}.png")
        print(f"{k}_{s} {time.time() - t:.0f}초", flush=True)
