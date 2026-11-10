# Troubleshooting Guide

## Common Issues

### Board Detection

#### Board not showing up in `hil detect`

**Symptoms:** `hil detect` returns empty list or doesn't show your board.

**Solutions:**
1. **Check USB connection**
   - Try a different USB cable (some cables are power-only)
   - Try a different USB port
   - Ensure the board is powered on

2. **Verify system recognizes the device**
   ```bash
   # macOS
   ls /dev/cu.* /dev/tty.*
   
   # Linux
   ls /dev/ttyUSB* /dev/ttyACM*
   
   # Windows (PowerShell)
   Get-WmiObject Win32_SerialPort | Select-Object Name,DeviceID
   ```

3. **Install USB drivers** (if needed)
   - CP210x: [Silicon Labs VCP drivers](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers)
   - CH340: [WCH drivers](http://www.wch-ic.com/downloads/CH341SER_ZIP.html)
   - FTDI: Usually pre-installed on modern systems

4. **Manual port specification**
   If auto-detection fails, explicitly set `port` in `hil.yaml`:
   ```yaml
   boards:
     - name: my-board
       target: esp32
       port: /dev/ttyUSB0  # or COM3 on Windows
   ```

---

### Flash Failures

#### "PlatformIO not found"

**Symptoms:** Error message: `PlatformIO (\`pio\`) not found on PATH.`

**Solution:**
```bash
pip install platformio
# Or: brew install platformio (macOS)
```

#### "Build failed" during flash

**Symptoms:** Flash operation stops with build errors.

**Diagnosis:**
1. Run PlatformIO manually to see full error:
   ```bash
   cd /path/to/your/firmware
   pio run -e esp32dev
   ```

2. Common causes:
   - Missing library dependencies
   - Syntax errors in C++ code
   - Wrong `platform` or `board` in `platformio.ini`

**Solution:** Fix the build errors in your firmware, then retry `hil flash`.

#### "Upload failed: could not open port"

**Symptoms:** Build succeeds but upload fails.

**Solutions:**
1. **Check permissions** (Linux):
   ```bash
   sudo usermod -a -G dialout $USER
   # Log out and back in
   ```

2. **Close other serial monitors**
   - Arduino IDE Serial Monitor
   - PlatformIO Serial Monitor
   - `screen` or `minicom` sessions

3. **Reset the board** by pressing the RESET button

4. **Try a different upload speed** in `platformio.ini`:
   ```ini
   upload_speed = 115200
   ```

---

### Crash Analysis

#### "addr2line returned no results"

**Symptoms:** Crash detected but no source locations in the report.

**Causes:**
- `firmware_elf` not set or path is wrong
- ELF file doesn't match the flashed firmware
- Toolchain not installed

**Solutions:**
1. **Set `firmware_elf` in hil.yaml**:
   ```yaml
   firmware_elf: .pio/build/esp32dev/firmware.elf
   ```

2. **Verify ELF exists**:
   ```bash
   ls /path/to/firmware/.pio/build/esp32dev/firmware.elf
   ```

3. **Install PlatformIO toolchain**:
   ```bash
   pio pkg install --global --tool platformio/toolchain-xtensa-esp32
   ```

#### "No crash detected" but firmware is clearly crashing

**Causes:**
- Crash pattern not recognized (non-standard format)
- Baud rate mismatch (garbled output)
- Serial buffer overflow

**Solutions:**
1. **Check baud rate** matches between firmware and `hil.yaml`:
   ```cpp
   // In firmware:
   Serial.begin(115200);
   ```
   ```yaml
   # In hil.yaml:
   baud_rate: 115200
   ```

2. **Add custom crash patterns** (future feature)

3. **Manually inspect serial log**:
   ```bash
   hil monitor --board my-board
   ```

---

### AI Self-Heal Loop

#### "ANTHROPIC_API_KEY not set"

**Symptoms:** `hil heal` command fails immediately.

**Solution:**
```bash
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

Or pass it via CLI:
```bash
hil heal --api-key sk-ant-your-key-here
```

#### Heal loop gives up after max cycles

**Symptoms:** "Heal loop ended: failed" after N cycles.

**Causes:**
- Bug is too complex for automated fixing
- Multiple unrelated crashes
- Hardware fault (not software)

**Solutions:**
1. **Review the AI analysis** in the crash panel
2. **Inspect the suggested fixes** in the logs
3. **Manually debug** using the crash reports as a starting point
4. **Increase `max_heal_cycles`** in hil.yaml (if you think it's close)

#### AI suggests fixes that don't compile

**Symptoms:** Fix is applied but next flash fails to build.

**Causes:**
- AI misunderstood the code context
- Incomplete type information
- C++ template complexity

**Solutions:**
1. **Manually revert** the bad fix:
   ```bash
   git diff  # See what changed
   git checkout -- path/to/file.cpp
   ```

2. **Provide more context** (future: custom prompt templates)

3. **Switch to a more capable model** in hil.yaml:
   ```yaml
   ai_model: claude-opus-5-5  # Most capable
   ```

---

### Dashboard / TUI

#### Dashboard WebSocket connection fails

**Symptoms:** Dashboard loads but shows "WebSocket disconnected".

**Solutions:**
1. **Check dashboard is running**:
   ```bash
   hil dashboard
   ```

2. **Firewall blocking localhost**:
   - Allow port 3000 in your firewall
   - Try a different port:
     ```yaml
     dashboard_port: 8080
     ```

3. **Browser CORS issue**:
   - Access via `http://localhost:3000`, not `http://127.0.0.1:3000`

#### TUI crashes or doesn't render properly

**Symptoms:** Terminal UI shows garbled output or crashes.

**Solutions:**
1. **Update Textual**:
   ```bash
   pip install --upgrade textual
   ```

2. **Use a modern terminal**:
   - macOS: iTerm2 or built-in Terminal.app
   - Linux: GNOME Terminal, Alacritty, or kitty
   - Windows: Windows Terminal (not CMD or PowerShell ISE)

3. **Set TERM correctly**:
   ```bash
   export TERM=xterm-256color
   ```

---

## Getting Help

If you're still stuck:

1. **Check existing issues**: [GitHub Issues](https://github.com/apandya55/hil_debug_workbench/issues)
2. **Open a new issue** with:
   - Your OS and Python version (`python --version`)
   - Board model and target chip
   - Full error message or `hil` command output
   - Contents of your `hil.yaml` (redact secrets)
3. **Include logs**: Run with verbose logging:
   ```bash
   hil --verbose heal
   ```
