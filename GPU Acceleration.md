# PR Title
Add CUDA acceleration plumbing for Whisper in VOXD

## Summary
- src/voxd/defaults/default_config.yaml: add a dedicated GPU block (enabled by default for CUDA) so new installs expose `gpu_enabled`, backend selection, device id, and layer count knobs.
- src/voxd/core/config.py: teach `AppConfig` about the new keys, resolve the CUDA-capable `whisper-cli`, and keep existing CPU defaults for upgraded users via the XDG config override.
- src/voxd/utils/core_runner.py: pass the GPU fields from config into `WhisperTranscriber` so the runtime decides between CPU, CUDA, or OpenCL automatically.
- src/voxd/core/transcriber.py: accept the GPU options, emit CUDA/OpenCL flags (`-ngl` and optional device selection) when enabled, and fall back cleanly to CPU.
- src/voxd/paths.py: expose helper resolvers for the whisper binary/model so config loading can pin to the rebuilt CUDA binary or fall back to the repo build.
- docs/setup (if applicable) and pr.md: document the CUDA rebuild workflow and the toolkit requirement.

## Testing
- `PATH=/opt/cuda/bin:$PATH cmake -S whisper.cpp -B whisper.cpp/build -DBUILD_SHARED_LIBS=OFF -DGGML_CUDA=ON`
- `PATH=/opt/cuda/bin:$PATH cmake --build whisper.cpp/build -j$(nproc)`
- `install -Dm755 whisper.cpp/build/bin/whisper-cli ~/.local/bin/whisper-cli`
- `whisper-cli --help` (verifies the rebuilt binary runs)
- Manual transcription run from VOXD UI/CLI with `gpu_enabled: true` confirmed `-ngl 999` is passed and CUDA initialization succeeds on a GTX 1080 Ti.

## Notes for Reviewers
- CUDA 11.8 is the latest toolkit that still supports Pascal (`sm_61`). Newer CUDA releases will fail to compile ggml with that architecture.
- Systems with glibc ≥ 2.40 need the usual `__THROW` annotation patch in `/opt/cuda/targets/x86_64-linux/include/crt/math_functions.h` until NVIDIA ships an update.
- User configs that already exist stay on CPU until they opt into the GPU fields or point `whisper_binary` at the CUDA build; fresh installs default to CUDA through the template.
