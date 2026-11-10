# Installation Guide

## Prerequisites

- **Python 3.11 or higher**
- **PlatformIO** (`pip install platformio`)
- **USB drivers** for your microcontroller (usually auto-detected on Linux/macOS; may require manual install on Windows)

## Install from PyPI (Recommended)

```bash
pip install hil-debug-workbench
```

## Install from Source

### For Development

```bash
git clone https://github.com/apandya55/hil_debug_workbench.git
cd hil_debug_workbench
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -e ".[dev]"
```

### For Production

```bash
git clone https://github.com/apandya55/hil_debug_workbench.git
cd hil_debug_workbench
pip install .
```

## Platform-Specific Notes

### macOS

USB serial drivers are usually pre-installed. For Silicon Labs CP210x chips:

```bash
# If needed:
brew install --cask silicon-labs-vcp-driver
```

### Linux

Add your user to the `dialout` group to access serial ports without sudo:

```bash
sudo usermod -a -G dialout $USER
# Log out and back in for the change to take effect
```

### Windows

- Install [PlatformIO](https://platformio.org/install) via the standalone installer
- USB drivers are usually installed automatically via Windows Update
- For CP210x chips: Download from [Silicon Labs](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers)

## Verify Installation

```bash
# Check that the CLI is installed
hil --version

# Detect connected boards
hil detect
```

## Optional: Anthropic API Key

For the AI self-healing loop, set your API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Or add to your shell profile (~/.bashrc, ~/.zshrc, etc.):

```bash
echo 'export ANTHROPIC_API_KEY=sk-ant-your-key-here' >> ~/.zshrc
```

## Troubleshooting

### "pio: command not found"

PlatformIO is not on your PATH. Install it:

```bash
pip install platformio
```

Or use the [PlatformIO installer](https://platformio.org/install).

### "Permission denied: /dev/ttyUSB0"

On Linux, add yourself to the `dialout` group (see Linux section above).

### "No module named 'hil_cli'"

The package is not installed. Run `pip install hil-debug-workbench` or `pip install -e .` in the project root.

### Board not detected

1. Check USB connection
2. Try a different USB cable (data, not power-only)
3. Verify the board appears in your system:
   - macOS: `ls /dev/cu.*`
   - Linux: `ls /dev/ttyUSB* /dev/ttyACM*`
   - Windows: Device Manager → Ports (COM & LPT)
4. Manually specify the port in `hil.yaml` if auto-detection fails
