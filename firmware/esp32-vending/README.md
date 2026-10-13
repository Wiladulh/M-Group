# Legacy PlatformIO scaffold — not the active firmware

The maintained ESP32-S3 Vending firmware is located at
[`esp32/vending/MGroupVending.ino`](../../esp32/vending/MGroupVending.ino).

Use the maintained sketch and its adjacent helper header in `esp32/vending/`.
This directory contains an older PlatformIO scaffold without the maintained
transaction and hardware implementation; it is not a supported build target.

For installation, wiring, server configuration, and physical validation steps,
see [the current Vending tutorial](../../esp32/vending/INSTALLATION_AND_WIRING.md)
and [the current Vending README](../../esp32/vending/README.md).

Do not use this scaffold to flash a production device.
