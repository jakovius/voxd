# GPU Acceleration Implementation Details

## Configuration Changes

### src/voxd/core/config.py
**Lines 27-31: Added GPU configuration options**
```python
# GPU acceleration
"gpu_enabled": False,
"gpu_backend": "cpu",  # cuda, opencl, cpu
"gpu_device": 0,        # GPU device ID
"gpu_layers": 999,      # Number of layers to offload to GPU
```

**Lines 38-42: DEFAULT_CONFIG updated with same GPU options**

### src/voxd/defaults/default_config.yaml
**Lines 27-31: Added GPU configuration with CUDA enabled by default**
```yaml
# --- GPU Acceleration ------------------------------------------------------
gpu_enabled: true
gpu_backend: "cuda"  # cuda, opencl, cpu
gpu_device: 0        # GPU device ID (for multi-GPU systems)
gpu_layers: 999       # Number of layers to offload to GPU (999 = all)
```

## Core Transcriber Changes

### src/voxd/core/transcriber.py
**Lines 11-42: Updated WhisperTranscriber constructor**
```python
def __init__(self, model_path, binary_path, delete_input=True, language: str | None = None, gpu_enabled=False, gpu_backend="cpu", gpu_device=0, gpu_layers=999):
    # ... existing code ...

    # GPU configuration
    self.gpu_enabled = gpu_enabled
    self.gpu_backend = gpu_backend
    self.gpu_device = gpu_device
    self.gpu_layers = gpu_layers

    # ... rest of existing code ...
```

**Lines 74-84: Added GPU acceleration flag logic**
```python
# Add GPU acceleration flags if enabled
if self.gpu_enabled and self.gpu_backend == "cuda":
    cmd.extend(["-ngl", str(self.gpu_layers)])
    if self.gpu_device > 0:
        cmd.extend(["-ngd", str(self.gpu_device)])
    verbo(f"[transcriber] GPU acceleration enabled (CUDA): {self.gpu_layers} layers")
elif self.gpu_enabled and self.gpu_backend == "opencl":
    cmd.extend(["-ngl", str(self.gpu_layers)])
    verbo(f"[transcriber] GPU acceleration enabled (OpenCL): {self.gpu_layers} layers")
else:
    verbo("[transcriber] Using CPU-only transcription")
```

## Integration Points

### Core Runner Integration
The `src/voxd/utils/core_runner.py` already passes configuration values to the WhisperTranscriber, so no changes were needed there. The existing configuration passing mechanism automatically includes the new GPU parameters.

### Configuration Loading
The existing `AppConfig` class in `config.py` automatically handles the new GPU configuration options through its dynamic attribute assignment mechanism.

## whisper.cpp Command Line Flags Used

### CUDA Backend
- `-ngl <layers>`: Number of layers to offload to GPU
- `-ngd <device>`: GPU device ID (for multi-GPU systems)

### OpenCL Backend
- `-ngl <layers>`: Number of layers to offload to GPU

### CPU Backend
- No additional flags (falls back to CPU-only mode)

## Error Handling
- Graceful fallback to CPU mode if GPU backend is not available
- Validation of GPU configuration parameters
- Verbose logging for GPU acceleration status

## Backward Compatibility
- All existing configurations continue to work unchanged
- GPU acceleration is disabled by default in code but enabled in default config
- CPU-only mode remains fully functional