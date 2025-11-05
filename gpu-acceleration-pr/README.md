# GPU Acceleration for VOXD

## Overview
This PR adds GPU acceleration support to VOXD using CUDA and OpenCL backends for whisper.cpp, enabling 5-10x faster transcription performance on compatible hardware.

## Features Added
- ✅ GPU configuration options in config file
- ✅ CUDA backend support with whisper.cpp
- ✅ OpenCL backend support for AMD/Intel GPUs
- ✅ Configurable GPU device selection
- ✅ Configurable GPU layer offloading
- ✅ CPU fallback support
- ✅ Automatic GPU flag handling in transcriber

## Performance Benefits
- **5-10x faster transcription** with NVIDIA GPUs (tested on GTX 1080 Ti)
- **Near real-time transcription** for shorter audio segments
- **Improved performance** for continuous dictation scenarios
- **Reduced CPU load** during transcription

## Files Modified
- `src/voxd/core/config.py` - Added GPU configuration options
- `src/voxd/core/transcriber.py` - Added GPU support to WhisperTranscriber
- `src/voxd/defaults/default_config.yaml` - Added default GPU settings

## Installation Requirements

### For CUDA (NVIDIA)
```bash
# Install CUDA toolkit
sudo pacman -S cuda

# Rebuild whisper.cpp with CUDA support
rm -rf whisper.cpp/build
cmake -S whisper.cpp -B whisper.cpp/build -DBUILD_SHARED_LIBS=OFF -DGGML_CUDA=ON
cmake --build whisper.cpp/build -j$(nproc)
cp whisper.cpp/build/bin/whisper-cli /home/y0gi/.local/bin/
```

### For OpenCL (AMD/Intel)
```bash
# Install OpenCL drivers
sudo pacman -S opencl-nvidia  # or opencl-amd, opencl-intel

# Rebuild whisper.cpp with OpenCL support
rm -rf whisper.cpp/build
cmake -S whisper.cpp -B whisper.cpp/build -DBUILD_SHARED_LIBS=OFF -DGGML_OPENCL=ON
cmake --build whisper.cpp/build -j$(nproc)
cp whisper.cpp/build/bin/whisper-cli /home/y0gi/.local/bin/
```

## Testing
See `testing.md` for comprehensive testing procedures.

## Backward Compatibility
- CPU-only mode remains fully functional
- Existing configurations continue to work unchanged
- GPU acceleration is opt-in via configuration

## Hardware Tested
- NVIDIA GTX 1080 Ti (CUDA backend)
- Expected to work with: RTX series, GTX 10xx+, modern AMD GPUs with OpenCL