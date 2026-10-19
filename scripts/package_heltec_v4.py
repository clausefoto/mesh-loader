#!/usr/bin/env python3
"""Package Heltec V4 pre-release outputs. Builds nothing and never flashes hardware.

Requires successful PlatformIO builds under build/{meshcore,meshtastic} and loader/.
Run: py -3.12 scripts/package_heltec_v4.py
"""
import hashlib
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESHTASTIC_VERSION = "2.8.1"
MESHCORE_VERSION = "1.18.0"
APP_LIMIT = 0x300000
FINAL_SIZE = 0x1000000

def file_at(path):
    if not path.is_file():
        raise RuntimeError(f"Missing binary: {path}")
    return path

def valid_app(path, max_size):
    data = file_at(path).read_bytes()
    if not 64 <= len(data) <= max_size or data[0] != 0xE9:
        raise RuntimeError(f"Invalid ESP32 image/size: {path} ({len(data)} bytes)")
    return data

def validate_partitions(binary):
    found = {}
    expected = {
        "nvs": (1,2,0x9000,0x6000),
        "otadata": (1,0,0xF000,0x2000),
        "loader": (0,0,0x20000,0x7D000),
        "meshcore": (0,0x10,0xA0000,0x300000),
        "meshtas": (0,0x11,0x3A0000,0x300000),
        "core_fs": (1,0x82,0x6A0000,0x4B0000),
        "tastic_fs": (1,0x82,0xB50000,0x4B0000)
    }
    for i in range(0, len(binary), 32):
        part = binary[i:i+32]
        if len(part) < 32 or part[:2] in (b'\xff\xff', b'\xeb\xeb'):
            break
        magic, typ, subtype, offset, size, name, flags = struct.unpack("<HBBII16sI", part)
        if magic != 0x50AA:
            raise RuntimeError(f"Invalid partition table record at offset {i}")
        found[name.split(b'\0')[0].decode("ascii")] = (typ, subtype, offset, size)
    if found != expected:
        raise RuntimeError(f"Partition table mismatch:\n{found}\nExpected:\n{expected}")

def main():
    mt_dir = ROOT / "build/meshtastic/.pio/build/heltec-v4"
    mc_path = ROOT / "build/meshcore/.pio/build/heltec_v4_companion_radio_ble/firmware.bin"
    loader_path = ROOT / "loader/.pio/build/heltec_v4/firmware.bin"
    # Old build artifacts can coexist after a rebuild. Select the newest
    # Meshtastic application, but only alongside its SAME-SUFFIX filesystem.
    app_prefix = f"firmware-heltec-v4-{MESHTASTIC_VERSION}."
    candidates = sorted(
        (p for p in mt_dir.glob(f"{app_prefix}*.bin")
         if not p.name.endswith(".factory.bin")),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("No Meshtastic application image for the expected version")
    app = candidates[0]
    suffix = app.name[len("firmware-heltec-v4-"):]
    filesystem = mt_dir / f"littlefs-heltec-v4-{suffix}"
    if not filesystem.is_file():
        raise RuntimeError(f"No matching LittleFS image for {app.name}: expected {filesystem.name}")
    print(f"Selected Meshtastic: {app.name} (newest matching build)")
    print(f"Selected LittleFS:   {filesystem.name}")
    mc = valid_app(mc_path, APP_LIMIT)
    mt = valid_app(app, APP_LIMIT)
    loader = valid_app(loader_path, 0x7D000)
    boot = valid_app(file_at(mt_dir / "bootloader.bin"), 0x8000)
    fs = file_at(filesystem).read_bytes()
    if len(fs) != 0x4B0000:
        raise RuntimeError("Meshtastic filesystem image is not 0x4B0000 bytes")

    out = ROOT / "build/release-heltec-v4"
    out.mkdir(parents=True, exist_ok=True)
    partitions = out / "partitions.bin"
    tool = ROOT / "partitions/16mb_default/partitions.csv"
    # Use ESP-IDF's installed partition-table encoder.
    generator = Path.home() / ".platformio/packages/framework-arduinoespressif32/tools/gen_esp32part.py"
    subprocess.run([sys.executable, str(generator), str(tool), str(partitions)], check=True)
    partition = partitions.read_bytes()
    validate_partitions(partition)

    merged = out / "heltec-v4-full-merged.bin"
    subprocess.run([
        sys.executable, "-m", "esptool", "--chip", "esp32s3", "merge-bin",
        "-o", str(merged),
        "0x0", str(mt_dir / "bootloader.bin"),
        "0x8000", str(partitions),
        "0x20000", str(loader_path),
        "0xA0000", str(mc_path),
        "0x3A0000", str(app),
        "0xB50000", str(filesystem)
    ], check=True)

    image = merged.read_bytes()
    if len(image) != FINAL_SIZE:
        raise RuntimeError(f"Unexpected full firmware size: {len(image)}")
    for address, payload, label in [
        (0x0, boot, "bootloader"),
        (0x8000, partition, "partitions"),
        (0x20000, loader, "loader"),
        (0xA0000, mc, "MeshCore"),
        (0x3A0000, mt, "Meshtastic"),
        (0xB50000, fs, "Meshtastic LittleFS")
    ]:
        if image[address:address+len(payload)] != payload:
            raise RuntimeError(f"Image verification failed: {label}")

    core_out = out / f"heltec-v4-meshcore-v{MESHCORE_VERSION}-update.bin"
    tastic_out = out / f"heltec-v4-meshtastic-v{MESHTASTIC_VERSION}-update.bin"
    shutil.copyfile(mc_path, core_out)
    shutil.copyfile(app, tastic_out)
    artifacts = [merged, core_out, tastic_out]
    checksums = out / "SHA256SUMS.txt"
    checksums.write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in artifacts
    ), encoding="utf-8")
    print("\nPASS: Merged layout and app images checked against exact source bytes.")
    for path in artifacts + [checksums]:
        print(f"{path.relative_to(ROOT)}: {path.stat().st_size:,} bytes")
    print("FULL merged image is DESTRUCTIVE: fresh installation ONLY.")
    print("Publishing these binaries is a separate manual step; no device was flashed.")

if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f"Packaging failed: {error}")
