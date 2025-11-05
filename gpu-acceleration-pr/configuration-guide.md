# GPU Acceleration Configuration Guide

## Configuration Options

### Basic GPU Configuration
Edit your `~/.config/voxd/config.yaml`:

```yaml
# --- GPU Acceleration ------------------------------------------------------
gpu_enabled: true          # Enable/disable GPU acceleration
gpu_backend: "cuda"       # Backend: "cuda", "opencl", or "cpu"
gpu_device: 0             # GPU device ID (for multi-GPU systems)
gpu_layers: 999           # Number of layers to offload (999 = all)
```

## Backend Options

### CUDA (NVIDIA GPUs)
- **Best performance** on NVIDIA hardware
- Requires CUDA toolkit installation
- Supports all modern NVIDIA GPUs (GTX 10xx+, RTX series)

```yaml
gpu_backend: "cuda"
```

### OpenCL (AMD/Intel GPUs)
- Good performance on AMD GPUs
- Works with Intel integrated graphics
- Requires OpenCL drivers

```yaml
gpu_backend: "opencl"
```

### CPU (Fallback)
- Software-only processing
- No additional requirements
- Compatible with all systems

```yaml
gpu_backend: "cpu"
```

## Advanced Configuration

### Multi-GPU Systems
If you have multiple GPUs, you can specify which one to use:

```yaml
gpu_device: 0  # First GPU
gpu_device: 1  # Second GPU
# etc.
```

### Layer Offloading
Control how much work is offloaded to the GPU:

```yaml
gpu_layers: 1    # Minimal GPU usage (good for testing)
gpu_layers: 500  # Partial GPU usage
gpu_layers: 999  # Maximum GPU usage (recommended)
```

### Memory Considerations
- **More layers = faster performance but more VRAM usage**
- GTX 1080 Ti: Full 999 layers uses ~800MB VRAM
- Reduce layers if you experience VRAM issues

## Detection and Verification

### Check Current Configuration
```bash
voxd --cfg
```

### Test GPU Detection
```bash
# Test with verbose output to see GPU status
voxd --record --verbose
```

### Check whisper.cpp GPU Support
```bash
whisper-cli --help | grep -E "(cuda|opencl)"
```

## Troubleshooting

### GPU Not Detected
1. Verify GPU drivers are installed
2. Rebuild whisper.cpp with GPU support
3. Check configuration syntax

### Performance Issues
1. Increase `gpu_layers` to 999
2. Verify GPU is not thermal throttling
3. Check GPU memory usage

### Fallback to CPU
If GPU acceleration fails, VOXD will automatically fall back to CPU processing and log a warning.

## Sample Configurations

### NVIDIA GTX/RTX (Recommended)
```yaml
gpu_enabled: true
gpu_backend: "cuda"
gpu_device: 0
gpu_layers: 999
```

### AMD Radeon GPU
```yaml
gpu_enabled: true
gpu_backend: "opencl"
gpu_device: 0
gpu_layers: 999
```

### Laptop with Optimus (Intel + NVIDIA)
```yaml
gpu_enabled: true
gpu_backend: "cuda"
gpu_device: 1  # Usually the discrete GPU
gpu_layers: 500  # Conservative VRAM usage
```

### CPU Only (Fallback)
```yaml
gpu_enabled: false
gpu_backend: "cpu"
gpu_device: 0
gpu_layers: 0
```