# STM32C011 Bring-Up Notes

## Passing Checks

- Klipper connects over USART1 on PA0/PA1 using AF4 at 115200 baud.
- MCU reports `MCU=stm32c011xx` and `CLOCK_FREQ=48000000`.
- Startup succeeds without the temporary PA4 blink marker.
- Klipper MCU restart command works.
- GPIO output toggles through Klipper.
- GPIO input pull-up and pull-down behavior passes through Klipper
  `gcode_button` / `QUERY_BUTTON`: pull-up reads pressed/high and
  pull-down reads released/low in the idle test.
- GPIO input tests need the Klipper button command module; `WANT_BUTTONS`
  is enabled for STM32C0 after seeing `Unknown command: buttons_ack` with
  `gcode_button`.
- I2C1 PB6/PB7 support is enabled in the test config and compiles locally.
- SPI1 PA5/PA6/PA7 support is enabled in the test config and compiles locally.
- ADXL345 works over SPI1; `ACCELEROMETER_QUERY` returns acceleration samples.
- ADS1220 support is enabled in the test config and `sensor_ads1220.c`
  compiles locally for STM32C0; hardware testing is pending.
- STM32C0 limited-code build keeps ADXL345 and ADS1220 enabled, while
  leaving other SPI/I2C sensor drivers disabled until tested so the firmware
  fits in 32 KiB flash.
- ADC support is enabled for STM32C0 external channels VIN0..VIN8 and
  compiles locally.
- MCU temperature support passes a Klipper/Mainsail sanity check. It maps to
  ADC VIN9 and uses TS_CAL1 at `0x1FFF7568`, calibrated at 30 C and VDDA
  3.0 V. Conversion currently uses the datasheet typical average slope of
  2.53 mV/C.

## Current Baseline

- Core boot, clock setup, scheduler/timer, watchdog, GPIO base support, and serial protocol are working.
- STM32C0 ADC is enabled for external channels and MCU temperature. External
  channels expose PA0..PA7 and PB0; `ADC_TEMPERATURE` maps to VIN9.
- STM32C0 I2C currently exposes only `i2c1_PB6_PB7` / `i2c1` for bring-up.
- STM32C0 SPI currently exposes only `spi1_PA6_PA7_PA5` / `spi1` for bring-up.
- STM32C0 VREFINT calibration is at `0x1FFF756A`, calibrated at 30 C and
  VDDA 3.0 V. Live VDDA compensation is not implemented yet.
- ADXL345 may return `0xff` on the first ID read, which was also seen on RP2040 with the same sensor; repeated queries succeed.
- PA11/PA12 are not valid USART TX/RX pins on STM32C011 according to the Port A alternate-function table; keep them available as GPIO or future board-specific use.
- Hardware PWM on PA8 as TIM1_CH1 AF2 passes a multimeter test:
  ~3.2 V at full scale, ~1.62 V at half scale, and 0 V when off. This
  matches the pressure board `light` net.
- TIM1 PWM normal outputs are mapped for PA8..PA11 as TIM1_CH1..CH4 AF2.
  PA9, PA10, and PA11 compile locally but still need hardware measurement.
- Additional PWM candidates include PA4 as TIM14_CH1 AF4 on the WeAct
  board. PA4 conflicts with SPI chip-select use on the pressure board, so
  avoid it there.

## Next Checks

- Test I2C when a supported I2C module is available.
- Test a basic external ADC pin with a known voltage or voltage divider.
- Test ADS1220 over SPI when the pressure-board ADC path is ready.
