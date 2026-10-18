# Heltec V4 — repeatable MeshCore update

This fork's `update-firmware` branch tracks MeshCore **companion-v1.18.0** and Meshtastic **v2.8.1**. The `heltec_v4` variant uses a 16 MB dual-boot layout. The original merged-image flashing command is intended for initial installation and **can overwrite MeshCore identity/settings**.

## Build only (Windows, Git Bash or PowerShell)

Use Python 3.12 and PlatformIO Core 6.1.19, as used for the tested firmware. From the repository root:

```bash
py -3.12 -m platformio --version
py -3.12 scripts/build_meshcore.py
```

The build script:

1. Makes a fresh `build/meshcore` copy of the pinned submodule.
2. Applies `patches/meshcore/common.patch` (SPIFFS `core_fs` mount, MAC adjustment, rollback hook).
3. Copies `partitions/16mb_default/partitions-meshcore.csv` and **explicitly selects** it for `heltec_v4_companion_radio_ble`. Merely copying the CSV is insufficient.
4. Compiles the firmware and checks its ESP32 image header, maximum size (3 MiB), and *decoded generated partition table*.

Result: `build/meshcore/.pio/build/heltec_v4_companion_radio_ble/firmware.bin`.

This is an **application image**, not a merged flash image. The script **never flashes anything**.

## Existing-device verification and backups

Before any device write, verify that the connected hardware uses the 16 MB Mesh Loader layout. Do **not** assume a COM port. Substitute your current port for `COM5` below, and close serial monitors.

```bash
py -3.12 -m platformio device list
mkdir -p backups
py -3.12 ~/.platformio/packages/tool-esptoolpy/esptool.py --chip esp32s3 --port COM5 read_flash 0x8000 0x1000 backups/heltec-v4-partitions.bin
py -3.12 ~/.platformio/packages/framework-arduinoespressif32/tools/gen_esp32part.py backups/heltec-v4-partitions.bin
```

For **this board/layout**, the on-device entries must include:

| Partition | Type | Address | Size |
|---|---|---|---|
| `loader` | factory app | `0x20000` | `0x7D000` |
| `meshcore` | ota_0 app | `0xA0000` | `0x300000` |
| `meshtas` | ota_1 app | `0x3A0000` | `0x300000` |
| `core_fs` | SPIFFS | `0x6A0000` | `0x4B0000` |
| `tastic_fs` | SPIFFS | `0xB50000` | `0x4B0000` |

Back up at least NVS, MeshCore filesystem, and the existing MeshCore application:

```bash
py -3.12 ~/.platformio/packages/tool-esptoolpy/esptool.py --chip esp32s3 --port COM5 --baud 115200 read_flash 0x9000 0x6000 backups/heltec-v4-nvs.bin
py -3.12 ~/.platformio/packages/tool-esptoolpy/esptool.py --chip esp32s3 --port COM5 --baud 115200 read_flash 0x6A0000 0x4B0000 backups/heltec-v4-core-fs.bin
py -3.12 ~/.platformio/packages/tool-esptoolpy/esptool.py --chip esp32s3 --port COM5 --baud 115200 read_flash 0xA0000 0x300000 backups/heltec-v4-meshcore-before-update.bin
```

Confirm exact backup sizes: 4096 bytes (partition table), 24576 (NVS), 4915200 (core_fs), 3145728 (MeshCore app). Retain backups securely off GitHub: they may contain private keys.

## Application-only upgrade (ONLY after verification)

The Mesh Loader firmware selects `ota_0` for MeshCore, and the verified layout places that app at `0xA0000`. For a board **confirmed to have the exact matching layout**, with backups saved and a successful build, the tested upgrade command is:

```bash
py -3.12 ~/.platformio/packages/tool-esptoolpy/esptool.py --chip esp32s3 --port COM5 --baud 115200 write_flash 0xA0000 build/meshcore/.pio/build/heltec_v4_companion_radio_ble/firmware.bin
```

This writes the app at `0xA0000` instead of the merged image at `0x0`. It does not intentionally write NVS, `core_fs`, partition table, or Meshtastic. The v1.17.1 → v1.18.0 app-only upgrade was verified on a Heltec V4 with both boot options working and prior MeshCore identity/settings intact. Preservation cannot be guaranteed for every future version or partition configuration.

**Never use `flash-merged` for a settings-preserving upgrade.** Future firmware may alter storage schemas or boot/OTA behavior; verify on each release before flashing. The build-time `meshcore` app offset `0x20000` is *not* the device's actual MeshCore application address.

## GitHub workflow

Make firmware version changes in a feature branch and test before merging to `main`. The build copies the submodule into `build/`, so do not commit dirty submodule working-tree contents. After updating through GitHub, run `git pull --ff-only origin update-firmware` on your local machine when your working directory permits it.
