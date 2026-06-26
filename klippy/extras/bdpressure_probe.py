# BD Pressure Probe Support
#
# This file may be distributed under the terms of the GNU GPLv3 license.
from . import ads1220
from . import load_cell
from . import load_cell_probe
from . import probe
from . import trigger_analog

ADS1220_MAX_COUNT = 0x7fffff
ADS1220_MIN_COUNT = -0x7fffff


class BDPressureLoadCell(load_cell.LoadCell):
    def __init__(self, config, sensor):
        self.bd_tare_counts = config.getint('reference_tare_counts')
        self.bd_range = config.getint('bd_range', minval=1)
        self.last_raw_counts = 0
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
            'bd_tare_counts': bd_tare_counts,
            'bd_tare_reference_delta_counts': bd_tare_reference_delta_counts,
            'bd_tare_reference_delta_percent': (
                bd_tare_reference_delta_percent),
            'load_cell_tare_counts': self.tare_counts,
            'last_raw_counts': self.last_raw_counts,
        })
        return status


class BDPressureProbeConfigHelper(load_cell_probe.LoadCellProbeConfigHelper):
    def __init__(self, config, load_cell_inst):
        self._printer = config.get_printer()
        self._load_cell = load_cell_inst
        self._sensor = load_cell_inst.get_sensor()
        self._tare_time_param = load_cell_probe.floatParamHelper(
            config, 'tare_time', default=4. / 60., minval=0.01, maxval=1.0)
        self._trigger_force_param = load_cell_probe.floatParamHelper(
            config, 'trigger_force', default=75., minval=10., maxval=2000.)
        self._force_safety_limit_param = load_cell_probe.floatParamHelper(
            config, 'force_safety_limit', minval=100., maxval=5000.,
            default=2000.)
        self._trigger_before_movement_retries = config.getint(
            'trigger_before_movement_retries', 3, minval=0)

    def get_safety_range(self, gcmd=None, tare_counts=None):
        counts_per_gram = self._load_cell.get_counts_per_gram()
        zero = self._load_cell.get_reference_tare_counts()
        if tare_counts is not None:
            zero = tare_counts
        safety_counts = int(counts_per_gram * self.get_safety_limit_grams(gcmd))
        safety_min = int(zero - safety_counts)
        safety_max = int(zero + safety_counts)
        sensor_min, sensor_max = self._load_cell.saturation_range()
        if safety_min <= sensor_min or safety_max >= sensor_max:
            cmd_err = self._printer.command_error
            raise cmd_err("Load cell force_safety_limit exceeds sensor range!")
        safety_min = self._load_cell.load_cell_to_sensor_counts(safety_min)
        safety_max = self._load_cell.load_cell_to_sensor_counts(safety_max)
        return min(safety_min, safety_max), max(safety_min, safety_max)

    def get_sensor_grams_per_count(self):
        grams_per_count = self.get_grams_per_count()
        return self._load_cell.load_cell_grams_per_count_to_sensor(
            grams_per_count)

    def get_sensor_counts(self, load_cell_counts):
        return self._load_cell.load_cell_to_sensor_counts(load_cell_counts)

    def get_trigger_force_grams(self, gcmd=None):
        return self._trigger_force_param.get(gcmd)

    def get_trigger_before_movement_retries(self, gcmd=None):
        if gcmd is None:
            return self._trigger_before_movement_retries
        return gcmd.get_int("TRIGGER_BEFORE_MOVEMENT_RETRIES",
                            self._trigger_before_movement_retries, minval=0)


class BDPressureProbingMove(load_cell_probe.LoadCellProbingMove):
    def __init__(self, config, load_cell_inst, mcu_trigger_analog,
                 param_helper, continuous_tare_filter_helper, config_helper):
        load_cell_probe.LoadCellProbingMove.__init__(
            self, config, load_cell_inst, mcu_trigger_analog, param_helper,
            continuous_tare_filter_helper, config_helper)
        self._last_trigger_before_movement_count = 0
        self._last_trigger_before_movement_retry_limit = 0

    def _pause_and_tare(self, gcmd):
        collector = self._start_collector()
        num_samples = self._config_helper.get_tare_samples(gcmd)
        results = collector.collect_min(num_samples)
        tare_samples = load_cell_probe.check_sensor_errors(
            results, self._printer)
        tare_counts = load_cell_probe.np.average(
            load_cell_probe.np.array(tare_samples)[:, 2].astype(float))
        self._continuous_tare_filter_helper.update_from_command(gcmd)
        self._load_cell.tare(tare_counts)
        safety_min, safety_max = self._config_helper.get_safety_range(
            gcmd, tare_counts)
        sensor_tare_counts = self._config_helper.get_sensor_counts(tare_counts)
        self._mcu_trigger_analog.set_raw_range(safety_min, safety_max)
        gpc = self._config_helper.get_sensor_grams_per_count()
        gpc *= load_cell_probe.FRAC_GRAMS_CONV
        sos_filter = self._mcu_trigger_analog.get_sos_filter()
        sos_filter.set_offset_scale(int(-sensor_tare_counts), gpc)
        trigger_val = self._config_helper.get_trigger_force_grams(gcmd)
        trigger_frac_grams = int(
            trigger_val * load_cell_probe.FRAC_GRAMS_CONV)
        self._mcu_trigger_analog.set_trigger("abs_ge", trigger_frac_grams)

    def probing_move(self, gcmd):
        if not self._load_cell.is_calibrated():
            raise self._printer.command_error("Load Cell not calibrated")
        toolhead = self._printer.lookup_object('toolhead')
        start_pos = toolhead.get_position()
        pos = list(start_pos)
        pos[2] = self._z_min_position
        if pos[2] >= start_pos[2]:
            raise self._printer.command_error(
                "Load cell probe move is not descending")
        speed = self._param_helper.get_probe_params(gcmd)['probe_speed']
        phoming = self._printer.lookup_object('homing')
        retry_limit = self._config_helper.get_trigger_before_movement_retries(
            gcmd)
        self._last_trigger_before_movement_count = 0
        self._last_trigger_before_movement_retry_limit = retry_limit
        while True:
            self._pause_and_tare(gcmd)
            collector = self._start_collector()
            try:
                epos = phoming.probing_move(
                    self._mcu_trigger_analog, pos, speed)
                break
            except self._printer.command_error as e:
                collector.stop_collecting()
                if "Probe triggered prior to movement" not in str(e):
                    raise
                if self._last_trigger_before_movement_count >= retry_limit:
                    raise
                self._last_trigger_before_movement_count += 1
        return epos, collector


class BDPressureTappingMove(load_cell_probe.TappingMove):
    def __init__(self, config, load_cell_probing_move, config_helper):
        load_cell_probe.TappingMove.__init__(
            self, config, load_cell_probing_move, config_helper)
        self._deactivate_on_each_sample = config.getboolean(
            'deactivate_on_each_sample', True)
        gcode_macro = self._printer.load_object(config, 'gcode_macro')
        self._activate_gcode = gcode_macro.load_template(
            config, 'activate_gcode', '')
        self._deactivate_gcode = gcode_macro.load_template(
            config, 'deactivate_gcode', '')
        self._multi = 'OFF'

    def start_probe_session(self):
        if not self._deactivate_on_each_sample:
            self._multi = 'FIRST'

    def end_probe_session(self):
        if not self._deactivate_on_each_sample:
            self._deactivate_probe(force=True)
            self._multi = 'OFF'

    def _run_probe_gcode(self, template, name):
        toolhead = self._printer.lookup_object('toolhead')
        start_pos = toolhead.get_position()
        template.run_gcode_from_command()
        if toolhead.get_position()[:3] != start_pos[:3]:
            raise self._printer.command_error(
                "Toolhead moved during probe %s script" % (name,))

    def _activate_probe(self):
        if self._multi == 'OFF' or self._multi == 'FIRST':
            self._run_probe_gcode(self._activate_gcode, 'activate_gcode')
            if self._multi == 'FIRST':
                self._multi = 'ON'

    def _deactivate_probe(self, force=False):
        if force or self._multi == 'OFF':
            self._run_probe_gcode(self._deactivate_gcode, 'deactivate_gcode')

    def run_tap(self, gcmd):
        self._activate_probe()
        try:
            return load_cell_probe.TappingMove.run_tap(self, gcmd)
        finally:
            self._deactivate_probe()


class BDPressureTapSession(load_cell_probe.TapSession):
    def start_probe_session(self, gcmd):
        load_cell_probe.TapSession.start_probe_session(self, gcmd)
        self._tapping_move.start_probe_session()
        return self

    def end_probe_session(self):
        try:
            load_cell_probe.TapSession.end_probe_session(self)
        finally:
            self._tapping_move.end_probe_session()


class BDPressureProbe(load_cell_probe.LoadCellPrinterProbe):
    def __init__(self, config):
        cfg_error = config.error
        try:
            import numpy as np
            load_cell_probe.np = np
        except:
            raise cfg_error("[bdpressure_probe] requires the NumPy module")
        self._printer = config.get_printer()
        sensor = ads1220.ADS1220(config)
        self._load_cell = BDPressureLoadCell(config, sensor)
        config_helper = BDPressureProbeConfigHelper(config, self._load_cell)
        mcu = self._load_cell.get_sensor().get_mcu()
        mcu_trigger_analog = trigger_analog.MCU_trigger_analog(sensor)
        cmd_queue = mcu_trigger_analog.get_dispatch().get_command_queue()
        sos_filter = trigger_analog.MCU_SosFilter(mcu, cmd_queue, 4)
        mcu_trigger_analog.setup_sos_filter(sos_filter)
        continuous_tare_filter_helper = (
            load_cell_probe.ContinuousTareFilterHelper(
                config, sensor, sos_filter))
        self._param_helper = probe.ProbeParameterHelper(config)
        self._cmd_helper = probe.ProbeCommandHelper(config, self)
        self._probe_offsets = probe.ProbeOffsetsHelper(config)
        load_cell_probing_move = BDPressureProbingMove(
            config, self._load_cell, mcu_trigger_analog,
            self._param_helper, continuous_tare_filter_helper, config_helper)
        self._tapping_move = BDPressureTappingMove(
            config, load_cell_probing_move, config_helper)
        tap_session = BDPressureTapSession(
            config, self._tapping_move, self._probe_offsets,
            self._param_helper)
        self._probe_session = probe.SampleAveragingHelper(
            config, self._param_helper, tap_session.start_probe_session)
        load_cell_probe.LoadCellProbeCommands(config, load_cell_probing_move)
        probe.HomingViaProbeHelper(config, self.get_offsets()[2])
        self._printer.add_object('probe', self)


def load_config(config):
    return BDPressureProbe(config)
