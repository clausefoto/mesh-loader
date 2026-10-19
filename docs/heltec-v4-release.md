# Heltec V4 dual-boot: safe updates and prerelease

This fork's `update-firmware` branch tracks MeshCore companion-v1.18.0 and Meshtastic v2.8.1 for the 16 MB Heltec V4. The source patches now select the factory Mesh Loader as the **next** boot target when either application starts; the running app is not interrupted. Both application-only updates and return-to-loader resets were tested on a Heltec V4. The new merged image still requires its own hardware test.

## Critical distinction

- **Existing Mesh Loader installation:** flash **application-only** binaries at the correct partition addresses. This avoids intentionally overwriting NVS, MeshCore storage, Meshtastic storage, the loader, and the partition table. Future storage compatibility is not guaranteed.
- **Fresh installation only:** `heltec-v4-full-merged.bin` flashed at `0x0` **overwrites all 16 MB**. It can erase both MeshCore and Meshtastic private keys, node identities, settings and channels. Do not use it as an upgrade.
- Never publish backups: both filesystems and NVS can contain private keys.

## Confirm the current flash layout

| Partition | Address | Size |
|---|---|---|
| NVS | 0x9000 | 0x6000 |
| OTA selection | 0xF000 | 0x2000 |
| Loader (factory) | 0x20000 | 0x7D000 |
| MeshCore | 0xA0000 | 0x300000 |
| Meshtastic | 0x3A0000 | 0x300000 |
| MeshCore filesystem | 0x6A0000 | 0x4B0000 |
| Meshtastic filesystem | 0xB50000 | 0x4B0000 |

The *build-time* app offset in each app's custom partition CSV is `0x20000`. This is **not** the on-device OTA app address.

## Safe PowerShell upgrade

Use Windows PowerShell (not Git Bash/MSYS2 for Meshtastic's ESP-IDF toolchain). Run from the repository root; substitute the actual device COM port. Close serial monitors.

Dry run (reads and validates the board's on-device partition table, checks image headers and sizes, **does not write anything**):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/upgrade-heltec-v4.ps1 -Port COM5 -MeshCorePath build/release-heltec-v4/heltec-v4-meshcore-v1.18.0-update.bin -MeshtasticPath build/release-heltec-v4/heltec-v4-meshtastic-v2.8.1-update.bin
```

Perform the application-only update (with automatic backups of shared NVS, both filesystems, `otadata`, and the device partition table before flashing either application):

```powershell
powershell -ExecutionPolicy Bypass -File scripts/upgrade-heltec-v4.ps1 -Port COM5 -MeshCorePath build/release-heltec-v4/heltec-v4-meshcore-v1.18.0-update.bin -MeshtasticPath build/release-heltec-v4/heltec-v4-meshtastic-v2.8.1-update.bin -Flash
```

Backups go under `backups/heltec-v4-YYYYMMDD-HHMMSS/`, ignored by Git. Ensure there is sufficient disk space for the filesystem backups. The script aborts on unexpected flash layout, invalid image size/header, or incomplete backup. Specify either application argument alone if upgrading only one.

After an upgrade, test: Loader → MeshCore → reset → Loader → Meshtastic → reset → Loader. If app doesn't load, stop; avoid a full-flash recovery that overwrites settings.

## Prepare a fresh prerelease from the successfully tested builds

Use Python 3.12 and PlatformIO Core 6.1.19, and ensure the prepared sources already contain the **loader-return** change (see `scripts/patch_prepared_loader_return.py`). Rebuild the app images with:

```powershell
py -3.12 -m platformio run -d build/meshcore -e heltec_v4_companion_radio_ble
py -3.12 -m platformio run -d build/meshtastic -e heltec-v4
py -3.12 -m platformio run -d loader -e heltec_v4
```

The rebuild commands don't flash the device. The Meshtastic build can be expensive on its first HybridCompile pass. Do **not** rerun `scripts/build_meshcore.py` unnecessarily: it replaces `build/meshcore` and recompiles from scratch.

Assemble all release binaries, regenerate the merged image, verify flash offsets and source contents, and write SHA-256 checksums:

```powershell
py -3.12 scripts/package_heltec_v4.py
```

Outputs:

- `build/release-heltec-v4/heltec-v4-full-merged.bin` (fresh install only)
- `build/release-heltec-v4/heltec-v4-meshcore-v1.18.0-update.bin`
- `build/release-heltec-v4/heltec-v4-meshtastic-v2.8.1-update.bin`
- `build/release-heltec-v4/SHA256SUMS.txt`

The Meshtastic LittleFS image is included in the **full** image but **not** published as a normal upgrade file. Replacing that filesystem can destroy saved Meshtastic identity and settings.

Mark the release as a **prerelease** until the regenerated merged image has been tested on hardware. The application-only upgrade and return-to-loader behavior have been tested; that does not prove the merged install is safe on other hardware or variants.
