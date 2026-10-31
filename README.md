# 🏎️ Formula Route Telemetry Converter

[![tests](https://github.com/DaniloSelliJunior/Route-Telemetry-Converter/actions/workflows/tests.yml/badge.svg)](https://github.com/DaniloSelliJunior/Route-Telemetry-Converter/actions/workflows/tests.yml)

> **Status:** integration with **SQLite** is currently **in development**.

Desktop tool that converts the raw binary logs (`.bin`) recorded by the ESP32 datalogger of the **[Formula Route UFSCar](https://www.formula.ufscar.br/)** Formula SAE team into **MoTeC i2** log files (`.ld`) and **CSV**, checks the quality of each log, computes session **KPIs** and exports a **report** (HTML/PDF).

It is the first piece of a broader initiative to restructure the team's data analysis tools. The goal is to deliver reliable, high-quality data that helps other engineering subsystems evaluate and validate vehicle dynamics during both the design and testing phases.

---

## ⚙️ Features

- **Robust binary parsing:** decodes the event-driven, mixed-rate `.bin` stream (little-endian, no global header) with `struct.unpack_from` over a single in-memory buffer. When the stream loses alignment (unknown ID, lost byte, garbage in the middle or at the end), the parser **resynchronises** on the next plausible packet instead of stopping, and reports every discarded byte range with its offset.
- **Timestamp checks:** `uint32` rollover is unwrapped; isolated packets with absurd timestamps are dropped; ESP32 resets and long logger pauses **split the log into segments**, each exported separately. A safety cap on the resampled grid prevents runaway memory use.
- **Log quality report:** per packet group, the real sample rate vs. the nominal one, gaps, out-of-order and repeated samples; discarded bytes and packets; `NaN`/`inf` count per channel; timestamp jumps and resets; and an **IMU unit check** (g vs. m/s², from the acceleration magnitude while the car is stopped; it only warns and never converts).
- **MoTeC `.ld` export:** 23 named channels with units, driver/vehicle/venue/event/session metadata and the `.bin` modification time as the log date. Optionally adds **derived channels** after the originals.
- **CSV export:** one CSV per packet group at native rates (no interpolation) or one unified CSV at 10/50/200 Hz; wide layout; *Padrão* (standard) and *Excel BR* profiles; a JSON metadata file alongside.
- **Batch conversion:** a whole folder of `.bin` files to `.ld` and/or CSV, with a per-file summary; a bad file never aborts the others.
- **Derived channels:** `Balanco_Freio_Pct`, `G_Combinado`, `Taxa_Acelerador`, `Distancia`, `Acel_Long_Velocidade`.
- **KPI engine:** driver (throttle, braking events, brake/throttle overlap), gearbox and engine (time per gear, shifts, RPM at shifts, RPM histogram, speed), dynamics (lateral/longitudinal g as the 99th percentile of the smoothed signal, g-g circle usage, yaw rate), reliability (engine temperature, oil pressure vs. RPM, battery voltage, lambda at high load), fuel consumption by linear regression, and 0-100 km/h / 0-75 m launches. Computed for the whole session and for **manually marked laps or stretches**, with an optional comparison between two sessions.
- **Report:** self-contained HTML (and PDF) with session summary, log quality, KPI table, g-g diagram, histograms, braking events, oil pressure vs. RPM and the session comparison.
- **Desktop GUI (Flet, interface in Portuguese):** tabs *Converter*, *CSV*, *KPIs* (table and charts) and *Configurações* (settings); **dark and light themes** (or follow the system), switchable at runtime; preferences persisted per user.
- **Safe writes:** every output goes to a temporary file and is renamed at the end; the GUI asks before overwriting.
- **Fast:** about 1 second to parse and convert 30 minutes of telemetry to `.ld` (see the benchmark below).

---

## ⚡ Usage Demonstration & Performance Benchmark

The video shows an earlier version of the desktop app converting a **synthetic 30-minute log** (23 channels multiplexed at 200, 50 and 10 Hz, ~558,000 packets, ~15 MB) generated with `bench_enduro.py`. The parser decodes the C-style struct payloads, resamples every channel to its nominal rate and writes the final `.ld` (~12.8 MB) in about 1 second.

https://github.com/user-attachments/assets/bc5bcd5b-2622-453d-a20c-4ac4a636f097

Measured on the same synthetic 30-minute log (Python 3.12, Linux; your numbers will vary):

| Step | Time |
|------|------|
| Read + decode `.bin` | ~0.6 s |
| Resample + write `.ld` (23 channels) | ~0.4 s (~0.5 s with derived channels) |
| Unified CSV, 50 Hz / 200 Hz | ~1.2 s / ~3.7 s |
| All KPIs (whole session) | ~0.4 s |

**Why it is fast:**

- The whole file is read into memory once and decoded with `struct.unpack_from`; there is no text parsing. Resynchronisation only kicks in on corrupted data and uses a regex scan for candidate IDs.
- Resampling, derived channels and KPIs are vectorised with NumPy instead of Python loops.
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
- The stream has no length field. An ID that is not in `packets.py` is treated as corrupted data: the parser skips to the next plausible packet (valid ID, timestamp consistent with the previous ones, next packet chained correctly) and reports the discarded bytes. The packet right before a corrupted stretch is also discarded, because there is no way to tell whether it was cut. A truncated packet at the very end of the file is discarded with a warning.
- Values are already engineering units and are **not rescaled**. Units are labels only; confirm them against the firmware (the IMU unit, g or m/s², is not confirmed yet; see the quality report).

To add or change a packet, edit `PACKETS` in `packets.py` (ID, struct format, nominal rate and channel names/units). Nothing else needs to change.

---

## 💻 Installation & Setup

```bash
git clone https://github.com/DaniloSelliJunior/Route-Telemetry-Converter.git
cd Route-Telemetry-Converter

python3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt        # app: flet + numpy
pip install -r requirements-report.txt # optional: HTML/PDF report and scatter charts (matplotlib)
```

Requires **Python 3.10+**. The core (parser, CSV, quality, KPIs) only needs NumPy; `matplotlib` is needed only for the report and for the g-g / oil-pressure scatter charts in the GUI.

| File | Contents |
|------|----------|
| `requirements.txt` | what the app needs (`flet`, `numpy`) |
| `requirements-report.txt` | `matplotlib` (report and scatter charts) |
| `requirements-dev.txt` | the two above + `pytest`, `pytest-cov` |
| `requirements-build.txt` | app + report + `pyinstaller` (used by `build.bat`) |

---

## 🖥️ Using the App

```bash
python app.py
```

The `.bin` is read **once**, when you select it; every tab reuses that parsed log.

1. **Telemetry file:** click the file area and select a `.bin`. The log is decoded and checked right away.
2. **Session data:** driver, vehicle, venue, event and session. They go into the `.ld` header and into the metadata of the CSV, KPI and report outputs.
3. **Log quality** (card above the tabs): warnings about sample rates, gaps, discarded bytes, `NaN`/`inf`, timestamp jumps/resets and the IMU unit check.

### Converter tab

Writes the MoTeC `.ld`. The *Incluir canais derivados no .ld* option appends the derived channels after the 23 logged ones. If the log was split into segments (timestamp reset or long pause), one `.ld` is written per segment.

### CSV tab

- **Unificado (unified):** one CSV with every channel on a common grid at 10, 50 (default) or 200 Hz, the same grid as the `.ld`. Continuous channels are linearly interpolated, `Marcha` holds its last value, and each group repeats its first/last value outside its own time range (as in the `.ld`).
- **Por grupo (per group):** one CSV per packet group with the samples exactly as logged (native rate, no interpolation), sorted by time.
- **Perfil (profile):** *Padrão* (`,` separator, `.` decimal, UTF-8) or *Excel BR* (`;` separator, `,` decimal, UTF-8 with BOM).
- **Batch (folder):** choose a folder and convert every `.bin` in it (not recursive) to `.ld` and/or CSV with the options above. Existing outputs are skipped unless *Sobrescrever arquivos existentes* is checked; the result lists each file as OK, skipped or error.

### KPIs tab

- **Limiares (thresholds):** the ones saved in the settings tab (*Usar os das Configurações*), or a JSON file picked for this session (*Escolher JSON*). *Salvar modelo* writes the current thresholds to a file you can edit.
- **Lap/stretch markers (optional):** a CSV with `nome,inicio_s,fim_s` (format below). KPIs are computed for the whole session and for each marked segment.
- **Compare with another session (optional):** pick a second `.bin`; the table shows A, B, delta and delta %.
- **Calcular KPIs** shows the table and charts for the selected segment: RPM and throttle histograms, time per gear and braking peaks as native bar charts; the g-g diagram and oil pressure vs. RPM as images (these need matplotlib).
- **Exportar KPIs** writes the KPI CSV and JSON (and the comparison CSV); **Gerar relatório** writes HTML and/or PDF.

### Configurações (settings) tab

- **Appearance:** *Sistema* (follow the OS), *Escuro* (dark) or *Claro* (light). Applied immediately, without restarting.
- **Defaults:** driver, vehicle and venue; CSV mode, rate and profile; default **output folder** for every output (empty = next to the `.bin`). Saved with *Salvar preferências*.
- **KPI thresholds:** a JSON editor with *Validar e salvar limiares* (invalid JSON, unknown keys and wrong types are rejected with a message) and *Restaurar padrões*.

Preferences are stored as JSON in the user configuration folder: `%APPDATA%\RouteTelemetryConverter` on Windows and `$XDG_CONFIG_HOME/RouteTelemetryConverter` (default `~/.config/RouteTelemetryConverter`) on Linux. Set `ROUTE_TELEMETRY_CONFIG_DIR` to use another folder. A missing, corrupted or partially invalid file never stops the app: the defaults are used and a warning is shown.

---

## 📄 Output Files

For an input `log.bin` (with several timestamp segments, `log` becomes `log_seg1`, `log_seg2`, ...):

| File | Contents |
|------|----------|
| `log.ld` | MoTeC i2 log (23 channels + optional derived channels) |
| `log_50Hz.csv` | unified CSV (rate in the name) |
| `log_<Group>.csv` | per-group CSV (`log_Chassi_IMU.csv`, `log_Pedais_Freios.csv`, ...) |
| `log_metadados.json` | CSV metadata: session fields, source file, version, mode, rate, profile, separator, decimal, encoding, file list |
| `log_kpis.csv` | KPIs, long format |
| `log_kpis.json` | KPIs + metadata, thresholds used, log quality report, version |
| `log_vs_other_comparacao.csv` | KPI deltas between two sessions |
| `log_relatorio.html` / `.pdf` | report |

**Wide CSV:** first column `tempo_s` (seconds since the first packet, 3 decimals), then one column per channel with the header `Name [unit]` (just `Name` when the channel has no unit). Values have 7 significant digits (the source data is `float32`). `NaN` and infinities are written as the text `nan`, `inf` and `-inf` in both profiles (pandas reads them as floats; Excel shows them as text).

**KPI CSV (long format):** columns `sessao, segmento, kpi, valor, unidade`. `segmento` is `sessao` for the whole log or the marker name.

**Comparison CSV:** columns `segmento, kpi, unidade, valor_a, valor_b, delta, delta_pct` (delta = B − A; empty when a KPI exists on one side only or A is zero for the percentage).

**Markers CSV** (input, your own format, not MoTeC's):

```csv
nome,inicio_s,fim_s
Volta 1,12.5,78.0
Volta 2,78.0,141.2
```

Times are seconds from the start of the log (the same origin as `tempo_s` and the `.ld`). `;` is also accepted as the separator, and then the decimal mark may be a comma. Blank lines and lines starting with `#` are ignored; names must be unique and `sessao` is reserved. Errors are reported with the line number.

**Thresholds JSON:** the same structure as the defaults (`derivados`, `piloto`, `motor`, `dinamica`, `confiabilidade`, `consumo`, `arrancada`); only the keys you change are needed, and keys starting with `_` are comments. Use *Salvar modelo* in the KPIs tab, or the editor in the settings tab, to get the full list.

---

## 🧩 Using the Core Without the GUI

```python
from pipeline import CsvOptions, SessionMeta, compute_log_kpis, load_log
from pipeline import convert_folder, write_csv_outputs, write_kpi_outputs, write_ld_outputs

log = load_log("log.bin")                  # parse + timestamp check + quality report
print(log.quality["avisos"], len(log.segments))

meta = SessionMeta(piloto="Driver", veiculo="FR2026", local="UFSCar")
write_ld_outputs(log, meta, include_derived=True)
write_csv_outputs(log, meta, CsvOptions(mode="unificado", freq_hz=50, profile="excel_br"))

sessions = compute_log_kpis(log)           # [(session name, KpiResult)]
write_kpi_outputs(log, meta, sessions)

items = convert_folder("logs/", meta, ld=True, csv=True)   # batch, one BatchItem per file
```

The lower layers are also usable on their own: `parser.parse_file` / `check_timestamps`, `exporter.write_ld`, `csv_export`, `quality.build_quality_report`, `derived.compute_derived` and `kpi.compute_kpis` (pure functions over `{name: (t, values)}`).

---

## 🧪 Testing

The test suite uses **pytest**. Every `.bin` input is built in code with `struct.pack` (`tests/builders.py`), so no binary fixtures are committed. KPI tests use synthetic signals with known results (constant throttle, injected braking events, noisy fuel level for the regression, constant-acceleration launches, and so on).

```bash
pip install -r requirements-dev.txt      # app + matplotlib + pytest + pytest-cov
pytest                                   # default run (slow tests excluded)
pytest -m slow                           # performance regression only
pytest -m ""                             # everything, including slow tests
pytest --cov --cov-report=term-missing   # coverage report
```

**494 tests:** 491 in the default run plus 3 `slow` performance tests.

What the suite covers:

- **Packet contract:** packed sizes, little-endian formats, rates, 23 unique channels.
- **Parser:** hand-written bytes, every payload field, type limits, mixed-rate interleaving; resynchronisation after a lost byte, garbage in the middle (at and inside a packet boundary), garbage at the end and unknown IDs at the start; discarded-byte accounting and warnings.
- **Timestamps:** rollover (single, double, across groups), the reproduced "isolated packet at 1,000,000,000 ms" case, resets and pauses split into segments, the grid safety cap.
- **Resampling, bad values and export:** grid sizes, interpolation vs. hold, out-of-order and repeated samples, `NaN`/`inf`; `.ld` read back with the vendored `ldparser` (metadata, header date, channels, derived channels); atomic writes; golden fingerprints of the `.ld`/debug-CSV output.
- **Quality report:** rate deviation, gaps, discards, non-finite values, jumps/resets, IMU unit check.
- **CSV:** layout, separators/decimals per profile, BOM, rates, hold, rollover, segments, metadata JSON, batch (bad file, skip/overwrite, output folder).
- **Derived channels and KPIs:** every KPI family with known results, segments, thresholds (defaults, overrides, validation), marker files, CSV/JSON outputs and comparisons.
- **Report:** chart data, self-contained HTML (no scripts or external resources, escaping), PDF; skipped automatically if matplotlib is missing.
- **Settings and themes:** load/save, invalid values, corrupted and binary files, write failures, thresholds editor; WCAG AA contrast (≥ 4.5:1) of every text color on every surface in both themes.
- **GUI helpers:** formatting and table/chart helpers from `app.py` (skipped if `flet` is not installed). The Flet interface itself is not covered by automated tests.
- **Performance (`slow`):** the 30-minute `bench_enduro.py` log (558,000 packets) must convert in under 15 s with full-length channels.

**Measured line coverage** (`pytest --cov`, default run, Python 3.12 on Linux): 98% for all non-GUI modules combined (each between 90% and 100%), 76% overall; `app.py` is at 13% because only its pure helpers are tested. The vendored `motec_lib/` is excluded.

GitHub Actions runs the default suite on **Python 3.10, 3.11 and 3.12** (Ubuntu) for every push and pull request to `main` (`.github/workflows/tests.yml`).

### Benchmark

```bash
python bench_enduro.py 30    # synthetic benchmark; argument = minutes of log (default 30)
python bench_enduro.py 1     # short 1-minute log to try the GUI (open bench_enduro.bin)
```

`bench_enduro.py` creates `bench_enduro.bin` and `bench_enduro.ld` in the current folder; delete them afterwards.

---

## 🪟 Building an Executable (experimental)

```bat
build.bat
```

Installs `requirements-build.txt` and uses `flet pack` (PyInstaller) to produce `dist\RouteTelemetryConverter.exe`, including matplotlib so the executable can generate reports. Build on the operating system you are targeting, since PyInstaller does not cross-compile. The vendored `motec_lib` and the `assets` folder are bundled explicitly.

---

## 🎨 Customizing the Look

Both color palettes (dark and light) live in `theme.py`; keep the role names and re-run `pytest tests/test_theme.py`, which checks text contrast. To show the team logo in the header, place a transparent PNG at `assets/logo.png`.

---

## 📁 Project Structure

```text
.
├── app.py              # Flet GUI (tabs: Converter, CSV, KPIs, Settings)
├── parser.py           # .bin decoding, resynchronisation, timestamp unwrap/segments, resampling
├── packets.py          # packet definitions (IDs, struct formats, rates, channels)
├── exporter.py         # .ld export (fast channel writer), resampled channels, debug CSV, atomic writes
├── csv_export.py       # wide CSV export (per group / unified), profiles, metadata JSON
├── quality.py          # log quality report
├── pipeline.py         # load once, write .ld/CSV/KPIs/report, batch conversion
├── signals.py          # signal helpers (smoothing, events, interpolation, percentiles)
├── derived.py          # derived channels
├── kpi/                # KPI engine
│   ├── core.py         #   runs every KPI module per segment
│   ├── driver.py  engine.py  dynamics.py  reliability.py  fuel.py  launch.py
│   ├── config.py       #   default (provisional) thresholds and JSON overrides
│   ├── segments.py     #   lap/stretch marker files
│   ├── model.py        #   KPI, Segment, KpiResult
│   └── output.py       #   KPI CSV/JSON and session comparison
├── report_data.py      # chart/table data for the GUI and the report (no matplotlib)
├── report.py           # HTML/PDF report and charts (matplotlib)
├── settings.py         # user preferences and KPI thresholds on disk
├── theme.py            # dark/light palettes
├── version.py          # app version (written into metadata)
├── motec_lib/          # vendored MoTeC .ld writer (see Credits)
├── assets/             # logo and static files
├── tests/              # pytest suite (synthetic logs built in code)
├── bench_enduro.py     # synthetic log generator and benchmark
├── build.bat           # Windows executable build
├── pyproject.toml      # pytest and coverage configuration
└── requirements*.txt   # app / report / dev / build dependencies
```

---

## ⚠️ Known Limitations

- **No GPS, steering angle, wheel speeds or suspension travel in the log.** Automatic lap detection, GPS sectors, track maps, tyre slip and roll gradient are therefore not possible; lap and sector KPIs depend on GPS and sensors the current log does not have. Laps and stretches can only be analysed through manual marker files.
- **KPI thresholds are provisional:** there are no real logs to calibrate them yet. They are configurable (settings tab or a JSON file).
- **IMU:** the unit (g or m/s²) and the mounting axes are not confirmed. The quality report only *suggests* the unit; values are never converted, and g KPIs are reported in the IMU's own unit. The longitudinal/lateral/yaw channels default to `Acel_X` / `Acel_Y` / `Gyro_Z` and are configurable.
- **Brake balance** comes from hydraulic pressure, not braking force, so it is indicative. It is `NaN` when not braking; check how MoTeC i2 displays those stretches.
- **Speed** comes from the ECU (probably a driven wheel), so wheelspin inflates launch distances. The launch start is the last sample below the rest threshold, which slightly underestimates launch times.
- **Corrupted data:** after a resynchronisation, the packet right before the corrupted stretch is discarded as well. `NaN`/`inf` from sensors are counted and reported but not removed.
- **Segmented logs** (timestamp reset or long pause) are exported as separate files; the KPI table in the GUI and the report charts show the first segment.
- **Resampled grid** (`.ld`, unified CSV, KPIs): each group repeats its first/last value outside its own time range. MoTeC channel frequencies are integers, and channels are stored with 0 displayed decimal places (full `float32` values are saved; i2 may round what it shows).
- **Sample-rate check:** timestamps have 1 ms resolution, so the median interval is coarse at 200 Hz; the mean rate (excluding gaps) is reported too.
- **Charts:** the pinned Flet version (0.25–0.27) has no scatter chart, so the g-g and oil-pressure charts are matplotlib images and need `requirements-report.txt`.

---

## 🚀 Roadmap

- **SQLite integration** (in development).
- **Calibrate KPI thresholds** with real track logs, and confirm the IMU unit and axes.
- **Signal processing & filtering:** low-pass filters and noise reduction before export.
- **Derived channels in the CSV export.**
- **Command-line interface** on top of `pipeline.py` (batch conversion is already available as a function and in the GUI).
- **Lap, sector and slip analysis** once GPS / wheel-speed / steering sensors are added to the car.

---

## 🛠️ Tech Stack

- **Language:** Python 3.10+
- **Libraries:** `struct` (binary unpacking), `numpy` (resampling, derived channels, KPIs), `flet` (GUI), `matplotlib` (report and scatter charts, optional)
- **Testing:** `pytest`, `pytest-cov`
- **Target software:** MoTeC i2 Standard / Pro, Excel, pandas

---

## 🙏 Credits

- [**MotecLogGenerator**](https://github.com/stevendaniluk/MotecLogGenerator) by Steven Daniluk (WTFPL), vendored in `motec_lib/` with the unused `cantools` import removed. `exporter.py` extends its `MotecLog` class with a fast array-based channel writer.
- [**ldparser**](https://github.com/gotzl/ldparser) by gotzl (GPL-3.0), vendored in `motec_lib/ldparser/`; it implements the binary `.ld` structures.

## 📄 License

This project bundles `ldparser`, which is licensed under the GNU GPL v3, so it is distributed under the **GPL-3.0** as well. See `LICENSE`.
