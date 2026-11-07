"""hil.yaml configuration schema and loader."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class BoardConfig(BaseModel):
    """Per-board configuration block."""

    name: str
    # Selects the toolchain and crash patterns.
    target: Literal["esp32", "esp32s2", "esp32s3", "rp2040"]
    # Leave empty to detect a connected board.
    port: str | None = None
    baud_rate: int = Field(default=115200, gt=0)
    # PlatformIO environment name (matches platformio.ini [env:NAME])
    pio_env: str
    pio_project_dir: str
    # Path to compiled ELF for addr2line; resolved relative to pio_project_dir when relative
    firmware_elf: str | None = None
    # Seconds with zero crashes before declaring success
    stability_window: int = Field(default=30, gt=0)
    # Hard limit on flash-analyze-fix cycles
    max_heal_cycles: int = Field(default=10, gt=0)

    @field_validator("pio_project_dir")
    @classmethod
    def project_dir_exists(cls, v: str) -> str:
        p = Path(v).expanduser()
        if not p.exists():
            raise ValueError(f"PlatformIO project directory not found: {v}")
        return str(p.resolve())

    def resolved_elf(self) -> Path | None:
        """Return absolute path to ELF, or None if not configured."""
        if self.firmware_elf is None:
            return None
        p = Path(self.firmware_elf)
        if not p.is_absolute():
            p = Path(self.pio_project_dir) / p
        return p.resolve() if p.exists() else None

    @property
    def is_esp32_family(self) -> bool:
        return self.target.startswith("esp32")

    @property
    def xtensa_toolchain_prefix(self) -> str:
        if self.target in ("esp32s2", "esp32s3"):
            return "xtensa-esp32s2-elf"
        return "xtensa-esp32-elf"

    @property
    def arm_toolchain_prefix(self) -> str:
        return "arm-none-eabi"

    @property
    def toolchain_prefix(self) -> str:
        if self.is_esp32_family:
            return self.xtensa_toolchain_prefix
        return self.arm_toolchain_prefix


class HilConfig(BaseModel):
    """Root configuration object parsed from hil.yaml."""

    version: int = Field(default=1, ge=1)
    boards: list[BoardConfig] = Field(min_length=1)
    dashboard_port: int = Field(default=3000, ge=1, le=65535)
    ai_model: str = "claude-opus-5-5"
    ai_max_tokens: int = Field(default=4096, gt=0)
    log_file: str | None = None

    @model_validator(mode="after")
    def unique_board_names(self) -> HilConfig:
        names = [board.name for board in self.boards]
        if len(names) != len(set(names)):
            raise ValueError("Board names must be unique")
        return self


def load_config(path: str | Path) -> HilConfig:
    """Parse a hil.yaml file and return a validated HilConfig."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Config not found: {p}")
    with p.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if raw is None:
        raise ValueError(f"Config is empty: {p}")
    return HilConfig.model_validate(raw)
