"""Tests for configuration parsing and validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hil_cli.config import BoardConfig, HilConfig, load_config


def test_board_config_defaults():
    """Test BoardConfig with minimal fields."""
    config = BoardConfig(
        name="test",
        target="esp32",
        pio_env="esp32dev",
        pio_project_dir="/tmp",
    )
    assert config.port is None
    assert config.baud_rate == 115200
    assert config.stability_window == 30
    assert config.max_heal_cycles == 10


def test_board_config_toolchain_prefix():
    """Test toolchain prefix selection."""
    esp32 = BoardConfig(name="e", target="esp32", pio_env="e", pio_project_dir="/tmp")
    assert esp32.toolchain_prefix == "xtensa-esp32-elf"
    assert esp32.is_esp32_family

    esp32s2 = BoardConfig(name="s2", target="esp32s2", pio_env="e", pio_project_dir="/tmp")
    assert esp32s2.toolchain_prefix == "xtensa-esp32s2-elf"

    rp2040 = BoardConfig(name="r", target="rp2040", pio_env="p", pio_project_dir="/tmp")
    assert rp2040.toolchain_prefix == "arm-none-eabi"
    assert not rp2040.is_esp32_family


def test_board_config_invalid_dir():
    """Test that nonexistent project dir is rejected."""
    with pytest.raises(ValidationError, match="not found"):
        BoardConfig(
            name="bad",
            target="esp32",
            pio_env="test",
            pio_project_dir="/nonexistent/path/123456",
        )


def test_hil_config_valid(sample_hil_config: HilConfig):
    """Test valid HilConfig."""
    assert sample_hil_config.version == 1
    assert len(sample_hil_config.boards) == 1
    assert sample_hil_config.dashboard_port == 3000
    assert sample_hil_config.ai_model == "claude-opus-5-5"


def test_load_config_from_yaml(tmp_path: Path, temp_project_dir: Path):
    """Test loading config from YAML file."""
    yaml_content = f"""
version: 1
boards:
  - name: test-board
    target: esp32
    pio_env: esp32dev
    pio_project_dir: {temp_project_dir}
    baud_rate: 115200
dashboard_port: 3000
ai_model: claude-opus-5-5
"""
    config_path = tmp_path / "test_hil.yaml"
    config_path.write_text(yaml_content)

    cfg = load_config(config_path)
    assert cfg.version == 1
    assert len(cfg.boards) == 1
    assert cfg.boards[0].name == "test-board"


def test_load_config_missing_file():
    """Test loading nonexistent config file."""
    with pytest.raises(FileNotFoundError):
        load_config("/nonexistent/config.yaml")


def test_resolved_elf_path(sample_board_config: BoardConfig, tmp_path: Path):
    """Test firmware_elf path resolution."""
    # No ELF configured
    assert sample_board_config.resolved_elf() is None

    # Absolute ELF path (nonexistent)
    sample_board_config.firmware_elf = str(tmp_path / "firmware.elf")
    assert sample_board_config.resolved_elf() is None

    # Create the ELF file
    elf = tmp_path / "firmware.elf"
    elf.write_bytes(b"\x7fELF")
    sample_board_config.firmware_elf = str(elf)
    resolved = sample_board_config.resolved_elf()
    assert resolved is not None
    assert resolved.exists()
