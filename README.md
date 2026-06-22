# BD Pressure Probe Project

## About This Project

This project explores using a BD pressure probe with Klipper's existing
`load_cell` and `load_cell_probe` infrastructure.

It started as an attempt to get the BD pressure sensor working on my printer,
and turned into a curiosity and discovery project about microcontrollers,
Klipper internals, and AI-assisted coding.

The original BD pressure project is
[markniu/bd_pressure](https://github.com/markniu/bd_pressure).
Hardware installation information and purchase links are available from that
project.
This project is not a substitute for the original firmware. It is experimental
work in progress.

The immediate goal is to make the BD pressure probe usable as a Z probe for
homing, tap probing, and bed mesh work. The longer-term goal is to collect
enough real force data to explore pressure advance behavior and other
toolhead-force experiments.

This is experimental work. The current implementation is intended to get the
hardware talking to Klipper and expose useful data so others can test, compare
logs, and help improve the approach.

## What Works

- Klipper can read the BD pressure probe through an ADS1220 ADC.
- The probe can be registered as `sensor_type: bdpressure_ads1220`.
- The BD sensor can feed Klipper's existing `load_cell_probe` path.
- Tare, trigger force, raw range checks, and MCU-side filtering are usable with
  the existing load cell probe commands.
- Status includes BD-specific values such as `bd_range`, `bd_tare_counts`, and
  `last_raw_counts` for debugging and charting.

## Configuration Used For Testing

The current test setup uses an STM32C011 with Klipper's extra low-level
configuration options enabled.

Firmware configuration used during testing:

![STM32C011 firmware configuration](stm32c0_docs/bdpressure_firmware_config.png)

Optional features used during testing:

![STM32C011 optional feature configuration](stm32c0_docs/bdpressure_optional_features.png)

Important enabled options:

- Micro-controller architecture: `STMicroelectronics STM32`
- Processor model: `STM32C011`
- Bootloader offset: `No bootloader`
- Clock reference: `Internal clock`
- Communication interface: `Serial (on USART1 PB7/PB6)`
- Baud rate: `250000`
- Software SPI bit banging
- ADS1220 ADC support
- Homing/probing events using analog sensors

Software serial is also an option and has been tested up to `38400` baud.

The board's CH340 USB path can be used to flash Klipper with
STM32CubeProgrammer over UART. `stm32flash` did not recognize the STM32C0 in
testing, so STM32CubeProgrammer was used instead.

## BDPressureADS1220

The main adapter is `BDPressureADS1220` in
`klippy/extras/bdpressure_probe.py`.

It wraps Klipper's normal ADS1220 sensor driver instead of replacing it. The
ADS1220 still performs the low-level ADC communication. The BD adapter catches
the ADS1220 sample batches, keeps the original raw BD count value for status,
and converts each sample into the wider count range expected by Klipper's load
cell code.

The BD pressure probe reports a much smaller useful raw-count span than a
typical load cell. Klipper's load cell code expects a larger ADS1220-style count
range, so `BDPressureADS1220` interpolates between two ranges:

- BD native range:
  `reference_tare_counts` to `reference_tare_counts + bd_range`
- Load-cell compatible range:
  `reference_tare_counts` to `reference_tare_counts + 0x7fffff`

That lets the existing load cell math consume the BD probe data without needing
to rewrite the higher-level probing logic.

The adapter also provides reverse conversion helpers. Those are important
because the host-side load cell code works in the expanded load-cell count
space, while the MCU raw range and trigger filter still need values in the
BD sensor's native raw-count space.

## Current Challenges

### Hardware

- SPI bit banging on the small STM32C0 test board adds latency.
- The STM32C0 is very resource constrained, so the firmware configuration has
  to stay minimal.
- Software serial is currently needed to keep the CH340 USB path usable, which
  means a separate USB-to-serial adapter is required for the Klipper connection.
- The ADS1220, pressure board, wiring, and MCU timing all need more testing
  across different printers and hardware setups.

### Software

- Multi-MCU synchronization can hit communication timeouts during Z homing.
  The current suspicion is that SPI bit banging on the STM32C0/ADS1220 path is
  adding enough latency to expose this.
- Thermal drift is the biggest known issue. Real print conditions can move the
  raw count baseline enough to affect repeated probing.
- More testing is needed around `tare_time`, `trigger_force`,
  `drift_filter_cutoff_frequency`, and probe retract timing.
- Filtering needs more tuning. The existing drift filter helps reject slow
  baseline changes, but the project may need better adaptive baseline handling
  for this sensor.
- Some failures only show up during real print-start conditions, after heat
  soak, bed mesh, and repeated taps.

The project is working well enough to invite testing, but it is not finished.
The next step is collecting more data and improving the tuning from real-world
printer behavior.

## Software Configuration

This is the configuration used during testing. It is not a recommended final
configuration, but it shows the custom BD pressure probe parameters and the
STM32C011 pin assignments that were used.

```ini
[load_cell_probe]
sensor_type: bdpressure_ads1220
tare_time: 0.3

spi_software_sclk_pin: stx32c011:PA5
spi_software_mosi_pin: stx32c011:PA2
spi_software_miso_pin: stx32c011:PA6
cs_pin: stx32c011:PA4
data_ready_pin: stx32c011:PA3

bd_range: 213500
input_mux: AIN0_AIN1
gain: 128
pga_bypass: False
sample_rate: 90
counts_per_gram: 150
reference_tare_counts: 1116500
trigger_force: 175
force_safety_limit: 5000
drift_filter_cutoff_frequency: 0.5

speed: 5
samples: 3
sample_retract_dist: 3
lift_speed: 3
samples_result: average
samples_tolerance: 0.1
samples_tolerance_retries: 3
```

Custom or important parameters:

- `sensor_type: bdpressure_ads1220` selects the BD pressure probe adapter.
- `bd_range` is the useful raw-count span of the BD pressure probe. The adapter
  scales this range into the larger ADS1220/load-cell count space.
- `reference_tare_counts` is the raw BD count baseline used as the zero point
  for the BD range conversion.
- `counts_per_gram` is still the load-cell force scale used by Klipper after
  the BD data has been converted into compatible counts.
- `tare_time` controls how long the probe averages samples before each probing
  move. This is important because the BD pressure probe can drift during real
  print conditions.
- `trigger_force` is the force threshold used to stop a probing move.
- `force_safety_limit` sets the raw-range safety window used while probing.
- `drift_filter_cutoff_frequency` enables the existing load-cell probe drift
  filter. Higher values reject more slow drift, but can also delay real trigger
  detection if pushed too far.
- The `spi_software_*`, `cs_pin`, and `data_ready_pin` values are the tested
  STM32C011 pin assignments for the ADS1220 connection.
