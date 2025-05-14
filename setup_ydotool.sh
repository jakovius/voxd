#!/usr/bin/env bash

# If required at any point, this script can be a run to install ydotool for typing support.
set -e

echo "=== 🧰 ydotool Setup Script (User-Level Daemon) ==="
echo "Required by Whisp app for typing support. Required on Wayland and will work for X11 too."

# 1. Install dependencies
echo "🔧 Installing build dependencies..."
sudo apt update
sudo apt install -y git cmake build-essential \
    libevdev-dev libudev-dev libconfig++-dev \
    libboost-program-options-dev

# 2. Clone and build ydotool
echo "📦 Cloning and building ydotool from source..."
git clone https://github.com/ReimuNotMoe/ydotool.git ~/ydotool-src
cd ~/ydotool-src
mkdir -p build && cd build
cmake ..
make -j$(nproc)
sudo make install
cd ~
rm -rf ~/ydotool-src

# 3. Create udev rule for uinput
echo "🛡️ Setting up udev rule for /dev/uinput access..."
echo 'KERNEL=="uinput", MODE="0660", GROUP="input"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules
sudo udevadm trigger

# 4. Add current user to input group
echo "👥 Adding user to input group (you may need to log out and back in)..."
sudo usermod -aG input "$USER"

# 5. Create systemd user service
echo "🧾 Creating systemd user service for ydotoold..."
mkdir -p ~/.config/systemd/user

cat <<EOF > ~/.config/systemd/user/ydotoold.service
[Unit]
Description=ydotool user daemon
After=default.target

[Service]
ExecStart=/usr/local/bin/ydotoold --socket-path=%h/.ydotool_socket --socket-own=%U:%G
Restart=on-failure

[Install]
WantedBy=default.target
EOF

# 6. Enable the user service
echo "⚙️ Enabling systemd user service..."
systemctl --user daemon-reload
systemctl --user enable ydotoold.service
systemctl --user start ydotoold.service

# 7. Add env var to shell config
SOCKET_LINE='export YDOTOOL_SOCKET="$HOME/.ydotool_socket"'
if ! grep -Fxq "$SOCKET_LINE" ~/.bashrc; then
    echo "$SOCKET_LINE" >> ~/.bashrc
    echo "✅ YDOTOOL_SOCKET added to ~/.bashrc"
fi
export YDOTOOL_SOCKET="$HOME/.ydotool_socket"

# 8. Final check
echo "🧪 Testing ydotool..."
sleep 2
ydotool type "🎉 Hello from your newly configured ydotool on Wayland!"

echo -e "\n✅ All done! Please **log out and log back in** to finalize group permissions."
