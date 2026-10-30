# eink

Bare-metal Rust firmware (`no_std`, `esp-hal`) for driving a Good Display
GDEM0397F81 4-color e-paper panel (black / white / red / yellow, SSD2677
controller) from an ESP32-S3 over SPI.

The driver handles init, power, solid fills, and full-frame image display.
`tools/img2epd.py` converts any image into the panel's 2-bits-per-pixel frame
format, with dithering.

## Wiring

| Panel | ESP32-S3 |
|-------|----------|
| SCK   | GPIO2    |
| MOSI  | GPIO1    |
| CS    | GPIO42   |
| DC    | GPIO41   |
| RST   | GPIO40   |
| BUSY  | GPIO39   |

SPI runs at 10 MHz, mode 0.

## Build and flash

Needs the Xtensa Rust toolchain ([espup](https://github.com/esp-rs/espup)) and
[espflash](https://github.com/esp-rs/espflash).

```sh
cargo run --release   # builds, flashes, and opens the serial monitor
```

## Displaying your own image

```sh
uv run tools/img2epd.py my-image.png -o photo.bin
cargo run --release
```

The controller's frame RAM is 800×680 but the visible glass is 800×480, so the
script pads the frame; `--image-pos` moves the image within it. The firmware
embeds `photo.bin` at compile time.
