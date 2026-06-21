# BD Pressure Probe Support
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import ads1220

ADS1220_MAX_COUNT = 0x7fffff
ADS1220_MIN_COUNT = -0x7fffff


class BDPressureADS1220:
    def __init__(self, config):
        self.ads = ads1220.ADS1220(config)
        self.reference_tare_counts = config.getint('reference_tare_counts')
        self.bd_range = config.getint('bd_range', minval=1)
        self.last_raw_counts = 0

    def _get_raw_count_range(self):
        return (self.reference_tare_counts,
                self.reference_tare_counts + self.bd_range)

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

    def load_cell_grams_per_count_to_sensor(self, grams_per_count):
        return grams_per_count * ADS1220_MAX_COUNT / self.bd_range

    def get_mcu(self):
        return self.ads.get_mcu()

    def setup_trigger_analog(self, trigger_analog_oid):
        self.ads.setup_trigger_analog(trigger_analog_oid)

    def get_samples_per_second(self):
        return self.ads.get_samples_per_second()

    def get_status(self, eventtime):
        status = self.ads.get_status(eventtime)
        bd_count_range = self._get_raw_count_range()
        status.update({
            'bd_range': self.bd_range,
            'bd_range_min': bd_count_range[0],
            'bd_range_max': bd_count_range[1],
            'bd_tare_counts': self.reference_tare_counts,
            'last_raw_counts': self.last_raw_counts
        })
        return status

    def lookup_sensor_error(self, error_code):
        return self.ads.lookup_sensor_error(error_code)

    def get_range(self):
        return (self.reference_tare_counts + ADS1220_MIN_COUNT,
                self.reference_tare_counts + ADS1220_MAX_COUNT)

    def add_client(self, callback):
        def _handle_batch(msg):
            data = msg.get('data')
            if data is None:
                return callback(msg)
            samples = []
            for row in data:
                raw_counts = row[1]
                load_cell_counts = self._to_load_cell_counts(raw_counts)
                samples.append((row[0], load_cell_counts, load_cell_counts))
            return callback({
                'data': samples,
                'errors': msg.get('errors', 0),
                'overflows': msg.get('overflows', 0),
            })
        self.ads.add_client(_handle_batch)


BDPRESSURE_SENSOR_TYPES = {
    'bdpressure_ads1220': BDPressureADS1220,
}
