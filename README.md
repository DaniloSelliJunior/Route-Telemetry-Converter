# 🏎️ Formula Route Telemetry Converter & Analysis Suite

This repository contains the core telemetry processing and data analysis software developed for the **Formula Route UFSCar** Formula Student team.

As part of a broader initiative to restructure the team's data analysis tools, this project bridges the gap between raw data acquisition and actionable engineering insights. The primary goal of this suite is to provide reliable, high-quality data to assist other engineering subsystems with vehicle dynamics evaluation and validation during both the design and testing phases.

---

## ⚙️ Current Features (Implemented)

The current version focuses on the foundational pipeline: extracting raw data and making it readable in industry-standard analysis software.

*   **Binary Data Parsing:** Reads and decodes raw binary telemetry streams directly from the vehicle's Data Acquisition (DAQ) system using Python.
*   **MoTeC Log Generation:** Automatically converts the parsed binary data into native **MoTeC i2** compatible log files (`.ld` / `.ldx`).
*   **Channel Mapping & Unit Conversion:** Maps raw sensor bytes to physical engineering units (e.g., RPM, wheel speeds, temperatures, suspension travel) for seamless integration into MoTeC workspaces.
*   **Timestamp Alignment:** Ensures accurate time-series synchronization across all sensor channels during the conversion process.
*   **Graphical User Interface (Flet GUI):** Intuitive desktop application built with Flet (Flutter for Python), enabling a seamless drag-and-drop workflow and real-time status tracking alongside the core CLI engine.
*   **High-Speed Processing:** Highly optimized execution capable of converting **30 minutes** of continuous telemetry data (spanning 23 sensor variables across multiple frequencies) into MoTeC logs in **under 1 second**.

---

### ⚡ Usage Demonstration & Performance Benchmark

*The video below demonstrates the Flet-based desktop application in action. In this benchmark, the application ingests a raw binary dump representing **30 minutes of continuous vehicle telemetry**. The dataset comprises 23 distinct sensor variables multiplexed at different sampling frequencies (up to 200 Hz). The underlying parsing engine efficiently decodes the C-style struct payloads, aligns the time-series data, applies physical unit conversions, and compiles the final `.ld` MoTeC log file in **under 1 second**. This high-throughput capability paired with an intuitive GUI ensures rapid turnaround times for vehicle dynamics validation.*

[Gravação de tela de 2026-10-11 01-15-31.webm](https://github.com/user-attachments/assets/bc5bcd5b-2622-453d-a20c-4ac4a636f097)

---


## 🚀 Roadmap (Planned Features)

The project is actively being expanded from a simple converter into a comprehensive data analysis and vehicle dynamics suite. The following features are in the development pipeline:

*   **CSV Data Export:** Implement robust export functionality to standard `.csv` format, allowing the data to be easily manipulated in Excel, Pandas, or external Machine Learning pipelines without relying solely on MoTeC.
*   **Automated KPI Engine:** Develop an automated module to calculate Key Performance Indicators (KPIs) immediately after data extraction. This will include:
    *   *Vehicle Dynamics:* Roll/pitch gradients, yaw rate analysis, and tire slip estimations.
    *   *Driver Performance:* Braking points, throttle application consistency, and sector times.
    *   *Reliability:* Peak temperatures, voltage drops, and pressure warnings.
*   **Signal Processing & Filtering:** Built-in low-pass filtering, moving averages, and noise reduction for raw sensor data before the final export.
*   **Custom Math Channels:** Generate new data channels via software (e.g., wheel lockup detection, brake bias calculation, steering velocity) directly in the Python script.
*   **Batch Processing Interface:** A Command Line Interface (CLI) or simple GUI to convert entire folders of track day logs at once, selecting specific output formats (MoTeC and/or CSV).

---

## 🛠️ Tech Stack & Architecture

*   **Language:** Python 3.x
*   **Core Libraries:** `struct` (binary unpacking), `numpy`, `pandas` (upcoming for CSV/KPIs)
*   **Target Software:** MoTeC i2 Standard / Pro

---

## 💻 Installation & Setup

1. Clone the repository:
   ```bash
   git clone [https://github.com/DaniloSelliJunior/](https://github.com/DaniloSelliJunior/)[YOUR_REPO_NAME].git
   ```

2. Navigate to the project directory:
  ```bash
  cd [YOUR_REPO_NAME]
  ```

3. Create a virtual environment and install dependencies:
  ```bash
  python -m venv venv
  source venv/bin/activate  # On Windows use `venv\Scripts\activate`
  pip install -r requirements.txt
  ```
