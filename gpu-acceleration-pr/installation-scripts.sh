#!/bin/bash
# GPU Acceleration Installation Scripts for VOXD

set -e

echo "=== VOXD GPU Acceleration Installation ==="
echo

# Detect GPU
detect_gpu() {
    if command -v nvidia-smi &> /dev/null; then
        echo "NVIDIA GPU detected:"
        nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits
        return 0
    elif lspci | grep -i "vga.*amd" &> /dev/null; then
        echo "AMD GPU detected"
        lspci | grep -i "vga.*amd"
        return 1
    elif lspci | grep -i "vga.*intel" &> /dev/null; then
        echo "Intel GPU detected"
        lspci | grep -i "vga.*intel"
        return 2
    else
        echo "No compatible GPU detected"
        return 3
    fi
}

# Install CUDA (NVIDIA)
install_cuda() {
    echo "Installing CUDA toolkit..."

    if [[ "$EUID" -eq 0 ]]; then
        pacman -S cuda
    else
        echo "Please run with sudo to install CUDA:"
        echo "sudo pacman -S cuda"
        return 1
    fi

    echo "CUDA installation complete"
    return 0
}

# Install OpenCL (AMD/Intel)
install_opencl() {
    echo "Installing OpenCL drivers..."

    if [[ "$EUID" -eq 0 ]]; then
        # Detect distribution and install appropriate OpenCL package
        if command -v pacman &> /dev/null; then
            echo "Detected Arch-based system"
            echo "Choose OpenCL package:"
            echo "1) opencl-nvidia (for NVIDIA)"
            echo "2) opencl-amd (for AMD)"
            echo "3) opencl-intel (for Intel)"
            read -p "Enter choice [1-3]: " choice

            case $choice in
                1) pacman -S opencl-nvidia ;;
                2) pacman -S opencl-amd ;;
                3) pacman -S opencl-intel ;;
                *) echo "Invalid choice"; return 1 ;;
            esac
        else
            echo "Unsupported distribution. Please install OpenCL manually."
            return 1
        fi
    else
        echo "Please run with sudo to install OpenCL drivers"
        return 1
    fi

    echo "OpenCL installation complete"
    return 0
}

# Rebuild whisper.cpp with GPU support
rebuild_whisper() {
    echo "Rebuilding whisper.cpp with GPU support..."

    # Detect whisper.cpp location
    WHISPER_DIR="whisper.cpp"
    if [[ ! -d "$WHISPER_DIR" ]]; then
        WHISPER_DIR="../whisper.cpp"
        if [[ ! -d "$WHISPER_DIR" ]]; then
            echo "Error: whisper.cpp directory not found"
            echo "Please run this from the VOXD directory or whisper.cpp directory"
            return 1
        fi
    fi

    echo "Found whisper.cpp at: $WHISPER_DIR"

    # Remove old build
    rm -rf "$WHISPER_DIR/build"

    # Detect GPU type for build flags
    if command -v nvidia-smi &> /dev/null; then
        echo "Building with CUDA support..."
        cmake -S "$WHISPER_DIR" -B "$WHISPER_DIR/build" -DBUILD_SHARED_LIBS=OFF -DGGML_CUDA=ON
    else
        echo "Building with OpenCL support..."
        cmake -S "$WHISPER_DIR" -B "$WHISPER_DIR/build" -DBUILD_SHARED_LIBS=OFF -DGGML_OPENCL=ON
    fi

    # Build
    cmake --build "$WHISPER_DIR/build" -j$(nproc)

    # Install to local bin
    mkdir -p ~/.local/bin
    cp "$WHISPER_DIR/build/bin/whisper-cli" ~/.local/bin/

    echo "whisper.cpp rebuild complete"
    return 0
}

# Configure VOXD for GPU
configure_voxd() {
    echo "Configuring VOXD for GPU acceleration..."

    CONFIG_DIR="$HOME/.config/voxd"
    CONFIG_FILE="$CONFIG_DIR/config.yaml"

    if [[ ! -f "$CONFIG_FILE" ]]; then
        echo "Error: VOXD config file not found at $CONFIG_FILE"
        echo "Please run VOXD at least once to create the config"
        return 1
    fi

    # Create backup
    cp "$CONFIG_FILE" "$CONFIG_FILE.backup.$(date +%Y%m%d_%H%M%S)"

    # Determine backend
    if command -v nvidia-smi &> /dev/null; then
        BACKEND="cuda"
    elif lspci | grep -i "vga.*amd\|vga.*radeon" &> /dev/null; then
        BACKEND="opencl"
    else
        BACKEND="cpu"
    fi

    echo "Using backend: $BACKEND"

    # Update config
    sed -i "s/gpu_enabled: false/gpu_enabled: true/" "$CONFIG_FILE" 2>/dev/null || true
    sed -i "s/gpu_backend: \"cpu\"/gpu_backend: \"$BACKEND\"/" "$CONFIG_FILE" 2>/dev/null || true

    # If gpu_enabled doesn't exist, add it
    if ! grep -q "gpu_enabled:" "$CONFIG_FILE"; then
        # Find a good place to insert the GPU config
        if grep -q "whisper_model_path:" "$CONFIG_FILE"; then
            sed -i "/whisper_model_path:/a\\n# GPU acceleration\\ngpu_enabled: true\\ngpu_backend: \"$BACKEND\"\\ngpu_device: 0\\ngpu_layers: 999" "$CONFIG_FILE"
        else
            echo -e "\n# GPU acceleration\ngpu_enabled: true\ngpu_backend: \"$BACKEND\"\ngpu_device: 0\ngpu_layers: 999" >> "$CONFIG_FILE"
        fi
    fi

    echo "VOXD configuration updated"
    return 0
}

# Verify installation
verify_installation() {
    echo "Verifying GPU acceleration setup..."

    # Check whisper-cli
    if ! command -v whisper-cli &> /dev/null; then
        echo "❌ whisper-cli not found in PATH"
        return 1
    fi

    # Check GPU support in whisper-cli
    if whisper-cli --help 2>&1 | grep -q "cuda"; then
        echo "✅ CUDA support detected in whisper-cli"
    elif whisper-cli --help 2>&1 | grep -q "opencl"; then
        echo "✅ OpenCL support detected in whisper-cli"
    else
        echo "⚠️  No GPU support detected in whisper-cli (may need rebuild)"
    fi

    # Check VOXD config
    CONFIG_FILE="$HOME/.config/voxd/config.yaml"
    if [[ -f "$CONFIG_FILE" ]]; then
        if grep -q "gpu_enabled: true" "$CONFIG_FILE"; then
            echo "✅ GPU acceleration enabled in VOXD config"
            echo "   Backend: $(grep 'gpu_backend:' "$CONFIG_FILE" | awk '{print $2}')"
            echo "   Layers: $(grep 'gpu_layers:' "$CONFIG_FILE" | awk '{print $2}')"
        else
            echo "❌ GPU acceleration not enabled in VOXD config"
        fi
    else
        echo "❌ VOXD config file not found"
    fi

    return 0
}

# Main menu
main_menu() {
    echo "Choose installation option:"
    echo "1) Full CUDA installation (NVIDIA)"
    echo "2) Full OpenCL installation (AMD/Intel)"
    echo "3) Rebuild whisper.cpp only"
    echo "4) Configure VOXD only"
    echo "5) Verify installation"
    echo "6) Auto-detect and install"
    echo "7) Exit"

    read -p "Enter choice [1-7]: " choice

    case $choice in
        1)
            detect_gpu
            install_cuda
            rebuild_whisper
            configure_voxd
            verify_installation
            ;;
        2)
            detect_gpu
            install_opencl
            rebuild_whisper
            configure_voxd
            verify_installation
            ;;
        3)
            rebuild_whisper
            ;;
        4)
            configure_voxd
            ;;
        5)
            verify_installation
            ;;
        6)
            echo "Auto-detecting GPU..."
            gpu_type=$(detect_gpu; echo $?)
            case $gpu_type in
                0)
                    echo "Installing CUDA support..."
                    install_cuda
                    rebuild_whisper
                    configure_voxd
                    verify_installation
                    ;;
                1|2)
                    echo "Installing OpenCL support..."
                    install_opencl
                    rebuild_whisper
                    configure_voxd
                    verify_installation
                    ;;
                *)
                    echo "No compatible GPU detected. Using CPU-only mode."
                    configure_voxd
                    ;;
            esac
            ;;
        7)
            echo "Exiting..."
            exit 0
            ;;
        *)
            echo "Invalid choice"
            main_menu
            ;;
    esac
}

# Check if running directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main_menu
fi