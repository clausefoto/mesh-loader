#!/usr/bin/env python3
"""Build the MeshCore companion image for Mesh Loader's Heltec V4 layout.

Run from the repository root:
    py -3.12 scripts/build_meshcore.py

This only builds firmware; it never flashes a device.
"""
from __future__ import annotations

import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "modules" / "meshcore"
TARGET = ROOT / "build" / "meshcore"
ENV = "heltec_v4_companion_radio_ble"
SECTION = f"[env:{ENV}]"
PATCH = ROOT / "patches" / "meshcore" / "common.patch"
CSV = ROOT / "partitions" / "16mb_default" / "partitions-meshcore.csv"
LIMIT = 0x300000
EXPECTED = {
    "nvs": (0x01, 0x02, 0x9000, 0x6000),
    "otadata": (0x01, 0x00, 0xF000, 0x2000),
    "meshcore": (0x00, 0x00, 0x20000, 0x300000),
    "core_fs": (0x01, 0x82, 0x6A0000, 0x4B0000),
}


def run(*args: str, cwd: Path | None = None) -> None:
    print("+", " ".join(str(x) for x in args), flush=True)
    subprocess.run([str(x) for x in args], cwd=cwd, check=True)


def check_partition_binary(path: Path) -> None:
    raw = path.read_bytes()
    found = {}
    for i in range(0, len(raw), 32):
        entry = raw[i:i + 32]
        if len(entry) < 32 or entry[:2] == b"\xff\xff":
            break
        magic, kind, subtype, offset, size, name, _flags = struct.unpack(
            "<HBBII16sI", entry
        )
        if magic != 0x50AA:
            raise RuntimeError(f"Unexpected partition entry at {i}: 0x{magic:04x}")
        label = name.split(b"\0", 1)[0].decode("ascii")
        found[label] = (kind, subtype, offset, size)
    if found != EXPECTED:
        raise RuntimeError(f"Wrong build-time partition table:\n{found}\nExpected:\n{EXPECTED}")
    print("Build-time partition table verified.", flush=True)


def main() -> None:
    if not (SOURCE / "platformio.ini").exists():
        raise RuntimeError("MeshCore submodule is missing. Initialize submodules first.")
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        SOURCE, TARGET,
        ignore=shutil.ignore_patterns(".git", ".pio", "__pycache__"),
    )
    run("git", "apply", "--check", str(PATCH), cwd=TARGET)
    run("git", "apply", str(PATCH), cwd=TARGET)
    shutil.copy2(CSV, TARGET / "partitions.csv")

    ini = TARGET / "variants" / "heltec_v4" / "platformio.ini"
    original = ini.read_text(encoding="utf-8")
    if original.count(SECTION) != 1:
        raise RuntimeError(f"Cannot uniquely locate {SECTION}")
    start = original.index(SECTION) + len(SECTION)
    end = original.find("\n[", start)
    if end == -1:
        end = len(original)
    section = original[start:end]
    if "board_build.partitions" in section:
        raise RuntimeError("Unexpected existing partition setting; inspect manually.")
    ini.write_text(
        original[:start] + "\nboard_build.partitions = partitions.csv" + original[start:],
        encoding="utf-8",
    )
    run(sys.executable, "-m", "platformio", "run", "-d", str(TARGET), "-e", ENV)

    output = TARGET / ".pio" / "build" / ENV
    image = output / "firmware.bin"
    partition = output / "partitions.bin"
    if not image.is_file() or not partition.is_file():
        raise RuntimeError("Missing firmware.bin or partitions.bin")
    if image.read_bytes()[:1] != b"\xe9":
        raise RuntimeError("Firmware does not have an ESP32 image header")
    size = image.stat().st_size
    if size > LIMIT:
        raise RuntimeError(f"Firmware too large: {size} > {LIMIT}")
    check_partition_binary(partition)
    print(f"PASS: {image.relative_to(ROOT)} ({size:,} bytes of {LIMIT:,})")
    print("Build only. Existing device partitions and keys were not changed.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Build failed: {exc}")
