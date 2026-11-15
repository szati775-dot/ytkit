# Third-party work used in this repo

All reused work is under permissive licences. Code we ported is credited in the file
that contains it; libraries we call are installed separately, not copied.

| Project | Licence | How it is used | Where |
|---|---|---|---|
| [librosa](https://github.com/librosa/librosa) | ISC | library: beat tracking, onsets, loudness | `editkit.py` (beats, scenes, plan) |
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | BSD-3-Clause | library: shot/cut detection | `editkit.py scenes` |
| [auto-editor](https://github.com/WyattBlue/auto-editor) | Unlicense | external tool: silence/motion trimming, Resolve export | `editkit.py trim` |
| [fake-bpy-module](https://github.com/nutti/fake-bpy-module) | MIT | type stubs of the Blender API, checked with mypy | `blender/check_bpy.py` |
| [Infinigen](https://github.com/princeton-vl/infinigen) (Princeton University) | BSD-3-Clause | **ported code**: grass tuft maths, boulder recipe, grass palette | `blender/nature.py`, licence in `blender/LICENSE-infinigen.txt` |
| [advertools](https://github.com/eliasdabbas/advertools) (Elias Dabbas) | MIT | idea re-implemented: absolute vs weighted word frequency | `ytkit.py seo` |
| [Mixpost](https://github.com/inovector/mixpost) (Inovector) | MIT | design re-implemented: Graph API version pinning, Page tokens, upload sessions | `ytkit.py post/social` (Facebook) |
| [stable-audio-tools](https://github.com/Stability-AI/stable-audio-tools) | MIT (code) | library; weights "Stable Audio Open Small" under the Stability AI Community License | `sfx/sfxgen.py` |

Instagram Reels and TikTok posting follow Meta's and TikTok's official API docs
(Mixpost's free edition only covers Facebook).

Rejected on licence or rules: MMAudio weights (CC-BY-NC), AudioCraft weights (CC-BY-NC),
cookie/login-automation uploaders (platform ToS), YouTube scrapers/downloaders (YouTube ToS),
AI tools run on War Thunder footage (Gaijin ToS 4.3.5).
