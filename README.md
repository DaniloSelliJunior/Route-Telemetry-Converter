# 🏎️ Formula Route Telemetry Converter

Desktop tool that converts the raw binary logs (`.bin`) recorded by the ESP32 datalogger of the **[Formula Route UFSCar](https://www.formula.ufscar.br/)** Formula SAE team into **MoTeC i2** log files (`.ld`).

It is the first piece of a broader initiative to restructure the team's data analysis tools. The goal is to deliver reliable, high-quality data that helps other engineering subsystems evaluate and validate vehicle dynamics during both the design and testing phases.

---

## ⚙️ Features

- **Binary parsing:** decodes the event-driven, mixed-rate `.bin` stream (little-endian, no global header) with `struct.unpack_from` over a single in-memory buffer.
- **MoTeC `.ld` export:** writes native logs that open in MoTeC i2, including driver, vehicle, venue, event and session metadata.
- **23 named channels with units:** four packet groups (IMU, pedals/brakes, fast engine, slow engine/fluids). The firmware already logs engineering-unit floats, so values are **not rescaled**; the converter only names the channels and attaches units.
- **Fixed-rate resampling:** the `.ld` format needs a fixed frequency per channel, so each packet group is resampled to its nominal rate (200 / 50 / 10 Hz) on a common time origin. Continuous channels use linear interpolation; discrete channels (gear) hold the last value, so a 2→3 shift never shows up as "gear 2.5".
- **Timestamp rollover handling:** the `uint32` millisecond counter wrapping (~49 days) is unwrapped; repeated timestamps keep the last sample.
- **Desktop GUI (Flet):** dark interface with a file picker, session metadata fields, progress bar and a result summary (packets, channels, log duration, conversion time, output path).
- **Fast:** about **1–2 seconds** for 30 minutes of telemetry (see the benchmark below).

---

## ⚡ Usage Demonstration & Performance Benchmark

The video shows the desktop app converting a **synthetic 30-minute log** (23 channels multiplexed at 200, 50 and 10 Hz, ~558,000 packets, ~15 MB) generated with `bench_enduro.py`. The parser decodes the C-style struct payloads, resamples every channel to its nominal rate and writes the final `.ld` (~12.8 MB) in about 1 second.

https://github.com/user-attachments/assets/bc5bcd5b-2622-453d-a20c-4ac4a636f097

**Why it is fast:**

- The whole file is read into memory once and decoded with `struct.unpack_from`; there is no text parsing.
- Resampling is vectorized with NumPy (`np.interp` / `np.searchsorted`) instead of Python loops.
- Channels are written to the `.ld` as ready-made `float32` arrays. The upstream library's default path creates one Python object per sample and appends in a loop, which took ~115 s for the same 30-minute log.

> Benchmark data is synthetic (mostly constant values) and measures speed and file size, not sensor behavior. Always check a real log in MoTeC i2.

---

## 📦 Input Format (`.bin`)

A continuous dump of packets with no global header, **little-endian**. Every packet starts with a 1-byte ID and a `uint32` timestamp (ms since logger start), followed by the payload.

| ID | Group | Rate | Size | `struct` | Channels (units) |
|----|-------|------|------|----------|------------------|
| `0x01` | Chassis & IMU | 200 Hz | 29 B | `<BI6f` | `Acel_X` `Acel_Y` `Acel_Z` (g) · `Gyro_X` `Gyro_Y` `Gyro_Z` (deg/s) |
| `0x02` | Pedals & Brakes | 50 Hz | 21 B | `<BI4f` | `Hall_Acelerador` (%) · `Hall_Freio` (%) · `Pressao_Freio_Diant` (PSI) · `Pressao_Freio_Tras` (PSI) |
| `0x03` | Fast Engine (ECU) | 50 Hz | 24 B | `<BIHb4f` | `RPM` (rpm) · `Marcha` (gear) · `TPS` (%) · `MAP` (kPa) · `Angulo_Ignicao` (deg) · `Velocidade` (km/h) |
| `0x04` | Slow Engine & Fluids | 10 Hz | 33 B | `<BI7f` | `Temp_Motor` (°C) · `Temp_Ar_IAT` (°C) · `Pressao_Oleo` (bar) · `Pressao_Combustivel` (bar) · `Tensao_Bateria` (V) · `Lambda_1` · `Nivel_Combustivel` (L) |

Rules the firmware must respect:

- Structs must be **packed** (no compiler padding). The packet sizes above are exact, and a misaligned layout shifts every value after the first field without raising an error.
- The stream has no length field, so the parser cannot skip an unknown ID: it stops there and reports a warning with the byte offset. A truncated packet at the end of the file is discarded with a warning.
- Units are labels only. Confirm them against the firmware (for example, whether the IMU reports g or m/s²).

To add or change a packet, edit `PACKETS` in `packets.py` (ID, struct format, nominal rate and channel names/units). Nothing else needs to change.

---

## 💻 Installation & Setup

```bash
git clone https://github.com/DaniloSelliJunior/YOUR_REPO_NAME.git
cd YOUR_REPO_NAME

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Requires **Python 3.10+**.

## 🖥️ Running

```bash
python app.py
```

1. Click the file area and select a `.bin` log.
2. Fill in the session fields (driver, vehicle, venue, event, session).
3. Click **Convert to .ld**. The `.ld` is saved next to the `.bin` with the same name.
4. Open it in MoTeC i2.

The core can also be used without the GUI:

```python
from parser import parse_file
from exporter import write_ld

result = parse_file("log.bin")
write_ld(result, "log.ld", driver="Driver", vehicle="FR2026", venue="UFSCar")
print(result.total_packets, result.warnings)
```

---

## 🧪 Tests & Benchmark

```bash
python test_parser.py        # parser, resampling, CSV helper and .ld write + read-back
python gerar_bin.py          # generates a small log_teste.bin to try the GUI
python bench_enduro.py 30    # synthetic benchmark; argument = minutes of log (default 30)
```

`bench_enduro.py` creates `bench_enduro.bin` and `bench_enduro.ld` in the current folder; delete them afterwards.

---

## 🪟 Building an Executable (experimental)

```bat
build.bat
```

Uses `flet pack` (PyInstaller) and produces `dist\RouteTelemetryConverter.exe`. Build on the operating system you are targeting, since PyInstaller does not cross-compile. The vendored `motec_lib` and the `assets` folder are bundled explicitly.

---

## 🎨 Customizing the Look

Colors live in the `THEME` block at the top of `app.py`. To show the team logo in the header, place a transparent PNG at `assets/logo.png`.

---

## 📁 Project Structure

```text
.
├── app.py             # Flet GUI
├── parser.py          # .bin decoding, timestamp unwrap, NumPy resampling
├── packets.py         # packet definitions (IDs, struct formats, rates, channels)
├── exporter.py        # .ld export (fast channel writer) and CSV helper
├── motec_lib/         # vendored MoTeC .ld writer (see Credits)
├── assets/            # logo and static files
├── test_parser.py     # tests
├── gerar_bin.py       # small sample log generator
├── bench_enduro.py    # synthetic benchmark
├── build.bat          # Windows executable build
└── requirements.txt
```

---

## ⚠️ Known Limitations

- Only `.ld` is exposed in the GUI. A basic CSV helper (`write_csv` in `exporter.py`) exists for debugging, with one channel per row.
- MoTeC channel frequencies are integers, and the upstream writer stores channels with 0 displayed decimal places. Values are saved in full as `float32`, but i2 may round what it displays until the channel's decimals are changed there.
- The converter does not yet detect timestamp resets (for example an ESP32 reboot mid-log) or large time jumps, and does not filter `NaN`/`inf` values from sensors.
- Parsing stops at the first unknown packet ID (see Input Format).

---

## 🚀 Roadmap

The project is being expanded from a converter into a data analysis and vehicle dynamics suite:

- **Log sanity checks:** detect timestamp resets and jumps, `NaN`/`inf` values and dropped packets, and report them in the GUI before export.
- **CSV export:** robust `.csv` output for Excel, Pandas or external Machine Learning pipelines, selectable in the GUI.
- **Batch processing:** a CLI and/or GUI mode to convert entire folders of track-day logs at once, choosing MoTeC and/or CSV output.
- **Automated KPI engine:** calculated right after extraction.
  - *Vehicle dynamics:* roll/pitch gradients, yaw rate analysis, tire slip estimation.
  - *Driver performance:* braking points, throttle application consistency, sector times.
  - *Reliability:* peak temperatures, voltage drops, pressure warnings.
- **Signal processing & filtering:** low-pass filters, moving averages and noise reduction before export.
- **Custom math channels:** derived channels such as wheel lockup detection, brake bias and steering velocity.

---

## 🛠️ Tech Stack

- **Language:** Python 3.10+
- **Libraries:** `struct` (binary unpacking), `numpy` (resampling and export), `flet` (GUI)
- **Planned:** `pandas` (CSV and KPIs)
- **Target software:** MoTeC i2 Standard / Pro

---

## 🙏 Credits

- [**MotecLogGenerator**](https://github.com/stevendaniluk/MotecLogGenerator) by Steven Daniluk (WTFPL), vendored in `motec_lib/` with the unused `cantools` import removed. `exporter.py` extends its `MotecLog` class with a fast array-based channel writer.
- [**ldparser**](https://github.com/gotzl/ldparser) by gotzl (GPL-3.0), vendored in `motec_lib/ldparser/`; it implements the binary `.ld` structures.

## 📄 License

This project bundles `ldparser`, which is licensed under the GNU GPL v3, so it is distributed under the **GPL-3.0** as well. See `LICENSE`.
