# GPU Acceleration Testing Guide

## Prerequisites
- Compatible GPU hardware (NVIDIA or AMD)
- Properly installed GPU drivers
- whisper.cpp built with GPU support

## Testing Procedure

### 1. Verify whisper.cpp GPU Support
```bash
# Check if whisper-cli was built with GPU support
whisper-cli --help | grep -i cuda
whisper-cli --help | grep -i opencl
```

### 2. Test GPU Configuration
```bash
# Check current VOXD configuration
voxd --cfg

# Verify GPU settings are present
grep -A 5 "gpu_" ~/.config/voxd/config.yaml
```

### 3. Performance Benchmark Tests

#### CPU Baseline Test
```bash
# Temporarily disable GPU
sed -i 's/gpu_enabled: true/gpu_enabled: false/' ~/.config/voxd/config.yaml

# Test transcription speed
time voxd --record
# Record a 30-second audio sample and note the transcription time
```

#### GPU Test (CUDA)
```bash
# Enable CUDA backend
sed -i 's/gpu_enabled: false/gpu_enabled: true/' ~/.config/voxd/config.yaml
sed -i 's/gpu_backend: "cpu"/gpu_backend: "cuda"/' ~/.config/voxd/config.yaml

# Test transcription speed
time voxd --record
# Record the same 30-second audio sample and compare transcription time
```

#### GPU Test (OpenCL - if applicable)
```bash
# Enable OpenCL backend
sed -i 's/gpu_backend: "cuda"/gpu_backend: "opencl"/' ~/.config/voxd/config.yaml

# Test transcription speed
time voxd --record
# Record the same audio sample and compare
```

### 4. Layer Offloading Tests

#### Test Different Layer Counts
```bash
# Test with minimal layers
sed -i 's/gpu_layers: 999/gpu_layers: 1/' ~/.config/voxd/config.yaml
voxd --record

# Test with partial layers
sed -i 's/gpu_layers: 1/gpu_layers: 500/' ~/.config/voxd/config.yaml
voxd --record

# Test with all layers (default)
sed -i 's/gpu_layers: 500/gpu_layers: 999/' ~/.config/voxd/config.yaml
voxd --record
```

### 5. Multi-GPU Test (if applicable)
```bash
# Test different GPU devices
sed -i 's/gpu_device: 0/gpu_device: 1/' ~/.config/voxd/config.yaml
voxd --record
```

### 6. Error Handling Tests

#### Invalid Backend Test
```bash
# Test with invalid backend
sed -i 's/gpu_backend: "cuda"/gpu_backend: "invalid"/' ~/.config/voxd/config.yaml
voxd --record
# Should fall back to CPU gracefully
```

#### Invalid Device Test
```bash
# Test with non-existent GPU device
sed -i 's/gpu_device: 0/gpu_device: 999/' ~/.config/voxd/config.yaml
voxd --record
# Should handle gracefully
```

## Expected Results

### Performance Benchmarks (GTX 1080 Ti example)
- **CPU-only**: ~2-3 seconds for 30-second audio
- **GPU CUDA**: ~0.3-0.5 seconds for 30-second audio (5-10x faster)
- **GPU OpenCL**: Variable, typically 2-4x faster than CPU

### Memory Usage
- **CPU-only**: ~500MB RAM
- **GPU CUDA**: ~300MB RAM + ~800MB VRAM
- **GPU OpenCL**: ~300MB RAM + ~600MB VRAM

### Success Indicators
- Transcription completes successfully
- Verbose output shows GPU acceleration status
- No error messages about GPU initialization
- Transcription quality remains identical to CPU mode

## Troubleshooting

### Common Issues

#### "CUDA not available" Error
```bash
# Check CUDA installation
nvidia-smi
nvcc --version

# Rebuild whisper.cpp with CUDA
cmake -S whisper.cpp -B whisper.cpp/build -DBUILD_SHARED_LIBS=OFF -DGGML_CUDA=ON
cmake --build whisper.cpp/build -j$(nproc)
```

#### "OpenCL not available" Error
```bash
# Check OpenCL installation
clinfo

# Rebuild whisper.cpp with OpenCL
cmake -S whisper.cpp -B whisper.cpp/build -DBUILD_SHARED_LIBS=OFF -DGGML_OPENCL=ON
cmake --build whisper.cpp/build -j$(nproc)
```

#### Performance No Better Than CPU
- Check GPU usage during transcription: `nvidia-smi` or `radeontop`
- Verify all layers are being offloaded: `gpu_layers: 999`
- Ensure GPU is not thermal throttling

## Test Report Template
```
## GPU Acceleration Test Report

**Hardware:**
- GPU: [Model]
- CPU: [Model]
- RAM: [Amount]

**Software:**
- OS: [Version]
- CUDA Version: [Version]
- Driver Version: [Version]

**Performance Results:**
- CPU Time: [seconds]
- GPU CUDA Time: [seconds]
- GPU OpenCL Time: [seconds]
- Speedup: [x]

**Issues Encountered:**
- [List any issues]

**Notes:**
- [Additional observations]
```