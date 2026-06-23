# BD Pressure Probe Support
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import ads1220
from . import load_cell
from . import load_cell_probe

ADS1220_MAX_COUNT = 0x7fffff
ADS1220_MIN_COUNT = -0x7fffff


class BDPressureLoadCell(load_cell.LoadCell):
    def __init__(self, config, sensor):
        self.bd_tare_counts = config.getint('reference_tare_counts')
        self.bd_range = config.getint('bd_range', minval=1)
        self.last_raw_counts = 0
        self.previous_bd_tare_counts = None
        self.bd_tare_delta_counts = None
        self.bd_tare_delta_percent = None
        load_cell.LoadCell.__init__(self, config, sensor)

    def _get_raw_count_range(self):
        return (self.bd_tare_counts, self.bd_tare_counts + self.bd_range)

    def _get_load_cell_count_range(self):
        return (self.reference_tare_counts,
                self.reference_tare_counts + ADS1220_MAX_COUNT)

    def _interpolate(self, value, src_range, dst_range):
        src_min, src_max = src_range
        dst_min, dst_max = dst_range
        src_span = float(src_max - src_min)
        dst_span = float(dst_max - dst_min)
        return int(dst_min + (value - src_min) * dst_span / src_span)

    def _to_load_cell_counts(self, raw_counts):
        self.last_raw_counts = raw_counts
        return self._interpolate(raw_counts, self._get_raw_count_range(),
                                 self._get_load_cell_count_range())

    def load_cell_to_sensor_counts(self, load_cell_counts):
        return self._interpolate(load_cell_counts,
                                 self._get_load_cell_count_range(),
                                 self._get_raw_count_range())

    def sensor_to_load_cell_counts(self, sensor_counts):
        return self._to_load_cell_counts(sensor_counts)

    def load_cell_grams_per_count_to_sensor(self, grams_per_count):
        return grams_per_count * ADS1220_MAX_COUNT / self.bd_range

    def saturation_range(self):
        return (self.reference_tare_counts + ADS1220_MIN_COUNT,
                self.reference_tare_counts + ADS1220_MAX_COUNT)

    def _percent_change(self, value, reference):
        if reference in (None, 0):
            return None
        return 100. * float(value - reference) / float(reference)

    def tare(self, tare_counts):
        previous_bd_tare_counts = None
        if self.tare_counts is not None:
            previous_bd_tare_counts = self.load_cell_to_sensor_counts(
                self.tare_counts)
        bd_tare_counts = self.load_cell_to_sensor_counts(tare_counts)
        self.previous_bd_tare_counts = previous_bd_tare_counts
        if previous_bd_tare_counts is None:
            self.bd_tare_delta_counts = None
            self.bd_tare_delta_percent = None
        else:
            self.bd_tare_delta_counts = (
                bd_tare_counts - previous_bd_tare_counts)
            self.bd_tare_delta_percent = self._percent_change(
                bd_tare_counts, previous_bd_tare_counts)
        load_cell.LoadCell.tare(self, tare_counts)

    def _sensor_data_event(self, msg):
        data = msg.get("data")
        errors = msg.get("errors")
        overflows = msg.get("overflows")
        if data is None:
            return None
        samples = []
        for row in data:
            load_cell_counts = self._to_load_cell_counts(row[1])
            samples.append([row[0], self.counts_to_grams(load_cell_counts),
                            load_cell_counts, self.tare_counts])
        msg = {'data': samples, 'errors': errors, 'overflows': overflows}
        self.clients.send(msg)
        return True

    def get_status(self, eventtime):
        status = load_cell.LoadCell.get_status(self, eventtime)
        bd_count_range = self._get_raw_count_range()
        bd_tare_counts = None
        bd_tare_reference_delta_counts = None
        bd_tare_reference_delta_percent = None
        if self.tare_counts is not None:
            bd_tare_counts = self.load_cell_to_sensor_counts(self.tare_counts)
            bd_tare_reference_delta_counts = (
                bd_tare_counts - self.bd_tare_counts)
            bd_tare_reference_delta_percent = self._percent_change(
                bd_tare_counts, self.bd_tare_counts)
        status.update({
            'bd_range': self.bd_range,
            'bd_range_min': bd_count_range[0],
            'bd_range_max': bd_count_range[1],
            'bd_reference_tare_counts': self.bd_tare_counts,
            'previous_bd_tare_counts': self.previous_bd_tare_counts,
            'bd_tare_counts': bd_tare_counts,
            'bd_tare_delta_counts': self.bd_tare_delta_counts,
            'bd_tare_delta_percent': self.bd_tare_delta_percent,
            'bd_tare_reference_delta_counts': bd_tare_reference_delta_counts,
            'bd_tare_reference_delta_percent': (
                bd_tare_reference_delta_percent),
            'load_cell_tare_counts': self.tare_counts,
            'last_raw_counts': self.last_raw_counts
        })
        return status


class BDPressureADS1220(load_cell_probe.LoadCellPrinterProbe):
    def _create_sensor(self, config):
        return ads1220.ADS1220(config)

    def _create_load_cell(self, config, sensor):
        return BDPressureLoadCell(config, sensor)


def load_config(config):
    return BDPressureADS1220(config)
