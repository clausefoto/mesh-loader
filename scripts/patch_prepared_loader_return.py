#!/usr/bin/env python3
"""Apply Mesh Loader return-on-reset changes to existing prepared build trees.

This modifies only C++ source inside build/ and is safe to run again.
Rebuild both app binaries afterward. No flashing is performed here.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CHANGES = [
    (
        ROOT / "build/meshcore/examples/companion_radio/main.cpp",
        "#include <Arduino.h>   // needed for PlatformIO\n",
        "#include <Arduino.h>   // needed for PlatformIO\n#include <esp_ota_ops.h>\n#include <esp_partition.h>\n",
        "void setup() {\n",
        """void setup() {
#if defined(ESP32)
  // Return to the factory Mesh Loader on the NEXT reset, not immediately.
  const esp_partition_t* loader_partition = esp_partition_find_first(
      ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_FACTORY, nullptr);
  if (loader_partition != nullptr) {
    esp_ota_set_boot_partition(loader_partition);
  }
#endif
""",
    ),
    (
        ROOT / "build/meshtastic/src/main.cpp",
        '#include "configuration.h"\n',
        '#include "configuration.h"\n#ifdef ARCH_ESP32\n#include <esp_ota_ops.h>\n#include <esp_partition.h>\n#endif\n',
        "void setup()\n{\n",
        """void setup()
{
#ifdef ARCH_ESP32
    // Return to factory Mesh Loader on the next reset; keep this app running.
    const esp_partition_t *loader_partition = esp_partition_find_first(
        ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_APP_FACTORY, nullptr);
    if (loader_partition != nullptr) {
        esp_ota_set_boot_partition(loader_partition);
    }
#endif
""",
    ),
]

def main():
    for file, inc_old, inc_new, setup_old, setup_new in CHANGES:
        if not file.is_file():
            raise SystemExit(f"Missing prepared build: {file}")
        source = file.read_text(encoding="utf-8")
        if setup_new in source and inc_new in source:
            print(f"ALREADY PATCHED: {file.relative_to(ROOT)}")
            continue
        if source.count(inc_old) != 1 or source.count(setup_old) != 1:
            raise SystemExit(f"Unexpected source layout; no changes made to {file}")
        if "esp_ota_set_boot_partition(loader_partition)" in source:
            raise SystemExit(f"Existing OTA boot selection code needs manual review: {file}")
        result = source.replace(inc_old, inc_new, 1).replace(setup_old, setup_new, 1)
        file.write_text(result, encoding="utf-8")
        print(f"PATCHED: {file.relative_to(ROOT)}")
    print("Now rebuild MeshCore and Meshtastic. App-only flash preserves their data partitions.")

if __name__ == "__main__":
    main()
