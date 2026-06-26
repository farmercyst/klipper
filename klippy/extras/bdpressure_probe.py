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
        self._min_probe_travel = config.getfloat(
            'minimum_probe_travel', 0.5, minval=0.)
        self._require_release_validation = config.getboolean(
            'require_release_validation', False)
        self._release_min_counts = config.getint(
            'release_validation_min_counts', 0, minval=0)
        self._release_retries = config.getint(
            'release_validation_retries', 3, minval=0)
        self._release_remaining_ratio = config.getfloat(
            'release_remaining_ratio', 0.35, minval=0., maxval=1.)
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

    def get_minimum_probe_travel(self, gcmd=None):
        if gcmd is None:
            return self._min_probe_travel
        return gcmd.get_float("MINIMUM_PROBE_TRAVEL", self._min_probe_travel,
                              minval=0.)

    def get_require_release_validation(self, gcmd=None):
        if gcmd is None:
            return self._require_release_validation
        return gcmd.get_int("REQUIRE_RELEASE_VALIDATION",
                            int(self._require_release_validation),
                            minval=0, maxval=1) != 0

    def get_release_min_counts(self, gcmd=None):
        if gcmd is None:
            return self._release_min_counts
        return gcmd.get_int("RELEASE_VALIDATION_MIN_COUNTS",
                            self._release_min_counts, minval=0)

    def get_release_retries(self, gcmd=None):
        if gcmd is None:
            return self._release_retries
        return gcmd.get_int("RELEASE_VALIDATION_RETRIES",
                            self._release_retries, minval=0)

    def get_release_remaining_ratio(self, gcmd=None):
        if gcmd is None:
            return self._release_remaining_ratio
        return gcmd.get_float("RELEASE_REMAINING_RATIO",
                              self._release_remaining_ratio,
                              minval=0., maxval=1.)

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
        self._last_probe_travel = None
        self._last_minimum_probe_travel = None
        self._last_probe_travel_too_short = False
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
        min_probe_travel = self._config_helper.get_minimum_probe_travel(gcmd)
        probe_travel = start_pos[2] - epos[2]
        self._last_probe_travel = probe_travel
        self._last_minimum_probe_travel = min_probe_travel
        self._last_probe_travel_too_short = probe_travel < min_probe_travel
        return epos, collector

    def get_last_probe_travel_info(self):
        too_short = self._last_probe_travel_too_short
        return {
            'probe_travel': self._last_probe_travel,
            'minimum_probe_travel': self._last_minimum_probe_travel,
            'probe_travel_too_short': too_short,
            'trigger_before_movement_count': (
                self._last_trigger_before_movement_count),
            'trigger_before_movement_retry_limit': (
                self._last_trigger_before_movement_retry_limit),
        }

    def get_last_trigger_time(self):
        get_last_trigger_time = getattr(
            self._mcu_trigger_analog, 'get_last_trigger_time', None)
        if get_last_trigger_time is None:
            return None
        return get_last_trigger_time()


class BDPressureTappingMove(load_cell_probe.TappingMove):
    def __init__(self, config, load_cell_probing_move, config_helper,
                 probe_params_helper, load_cell_inst):
        load_cell_probe.TappingMove.__init__(
            self, config, load_cell_probing_move, config_helper)
        self._probe_params_helper = probe_params_helper
        self._load_cell = load_cell_inst
        self._last_release_check = self._empty_release_check()
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

    def _avg(self, values):
        return float(sum(values)) / float(len(values))

    def _new_release_check(self, **overrides):
        release_check = {
            'sample_count': 0,
            'pre_avg_counts': None,
            'trigger_raw_counts': None,
            'post_retract_avg_counts': None,
            'trigger_delta_counts': None,
            'retract_delta_counts': None,
            'release_valid': False,
            'release_attempt': 0,
            'release_retract_dist': 0.,
            'release_retract_sample_count': 0,
            'release_detected_dist': None,
            'release_remaining_ratio': None,
            'release_remaining_load_counts': None,
            'release_trigger_load_counts': None,
            'probe_travel': None,
            'minimum_probe_travel': None,
            'probe_travel_too_short': False,
            'trigger_before_movement_count': 0,
            'trigger_before_movement_retry_limit': 0,
            'release_skipped': False,
            'release_skip_reason': '',
        }
        release_check.update(overrides)
        return release_check

    def _empty_release_check(self):
        return self._new_release_check()

    def _raw_counts(self, samples):
        return [self._load_cell.load_cell_to_sensor_counts(row[2])
                for row in samples]

    def _window_avg(self, samples):
        if not samples:
            return None
        return self._avg(self._raw_counts(samples))

    def _sample_at_time(self, samples, sample_time):
        if not samples:
            return None
        best_sample = samples[0]
        best_delta = abs(samples[0][0] - sample_time)
        for sample in samples[1:]:
            delta = abs(sample[0] - sample_time)
            if delta < best_delta:
                best_sample = sample
                best_delta = delta
        return self._load_cell.load_cell_to_sensor_counts(best_sample[2])

    def _skipped_release_check(self, samples, reason):
        return self._new_release_check(
            sample_count=len(samples),
            release_valid=True,
            release_skipped=True,
            release_skip_reason=reason)

    def _base_release_check(self, samples, trigger_time):
        pre_samples = []
        trigger_raw = None
        if trigger_time:
            pre_samples = [s for s in samples if s[0] < trigger_time]
            trigger_raw = self._sample_at_time(samples, trigger_time)
        if not pre_samples:
            pre_samples = samples[:max(1, len(samples) // 3)]
        if trigger_raw is None:
            trigger_raw = self._load_cell.load_cell_to_sensor_counts(
                samples[-1][2])
        pre_avg = self._window_avg(pre_samples)
        return pre_avg, trigger_raw

    def _build_release_check(self, samples, pre_avg, trigger_raw,
                             post_avg, retract_dist, remaining_ratio,
                             retract_sample_count=0,
                             release_detected_dist=None):
        result = self._new_release_check(
            sample_count=len(samples),
            pre_avg_counts=pre_avg,
            trigger_raw_counts=trigger_raw,
            post_retract_avg_counts=post_avg,
            release_retract_dist=retract_dist,
            release_retract_sample_count=retract_sample_count,
            release_detected_dist=release_detected_dist,
            release_remaining_ratio=remaining_ratio)
        if pre_avg is None or trigger_raw is None or post_avg is None:
            return result
        trigger_delta = trigger_raw - pre_avg
        retract_delta = post_avg - trigger_raw
        trigger_load = abs(trigger_delta)
        remaining_load = abs(post_avg - pre_avg)
        ratio_released = (
            trigger_load > 0
            and remaining_load <= trigger_load * remaining_ratio)
        release_valid = ratio_released
        result.update({
            'trigger_delta_counts': trigger_delta,
            'retract_delta_counts': retract_delta,
            'release_remaining_load_counts': remaining_load,
            'release_trigger_load_counts': trigger_load,
            'release_valid': release_valid,
        })
        return result

    def _apply_release_min_counts(self, release_check, min_counts):
        retract_delta = release_check['retract_delta_counts']
        if retract_delta is not None:
            release_check['release_valid'] = (
                release_check['release_valid']
                and abs(retract_delta) >= min_counts)
        return release_check

    def _apply_probe_travel_info(self, release_check):
        release_check.update(
            self._load_cell_probing_move.get_last_probe_travel_info())
        return release_check

    def _retract_dist_at_time(self, sample_time, start_time, end_time,
                              retract_dist):
        if sample_time is None:
            return None
        if sample_time <= start_time:
            return 0.
        if sample_time >= end_time:
            return retract_dist
        move_time = end_time - start_time
        if move_time <= 0.:
            return retract_dist
        return retract_dist * (sample_time - start_time) / move_time

    def _smooth_release_check(self, trigger_samples, retract_samples, pre_avg,
                              trigger_raw, retract_dist, start_time,
                              end_time, remaining_ratio):
        samples = list(trigger_samples)
        samples.extend(retract_samples)
        if not retract_samples:
            return self._build_release_check(
                samples, pre_avg, trigger_raw, None, retract_dist,
                remaining_ratio)
        best_check = None
        best_remaining_load = None
        for idx in range(len(retract_samples)):
            window = retract_samples[idx:idx + 3]
            post_avg = self._window_avg(window)
            sample_time = window[-1][0]
            sample_dist = self._retract_dist_at_time(
                sample_time, start_time, end_time, retract_dist)
            release_check = self._build_release_check(
                samples, pre_avg, trigger_raw, post_avg, sample_dist,
                remaining_ratio, retract_sample_count=len(retract_samples),
                release_detected_dist=sample_dist)
            remaining_load = release_check['release_remaining_load_counts']
            if remaining_load is not None and (
                    best_remaining_load is None
                    or remaining_load < best_remaining_load):
                best_remaining_load = remaining_load
                best_check = release_check
            if release_check['release_valid']:
                return release_check
        if best_check is not None:
            best_check['release_retract_dist'] = retract_dist
            best_check['release_detected_dist'] = None
            return best_check
        return self._build_release_check(
            samples, pre_avg, trigger_raw, None, retract_dist,
            remaining_ratio, retract_sample_count=len(retract_samples))

    def _run_candidate_tap(self, gcmd):
        epos, collector = self._load_cell_probing_move.probing_move(gcmd)
        toolhead = self._printer.lookup_object('toolhead')
        toolhead.flush_step_generation()
        trigger_time = self._load_cell_probing_move.get_last_trigger_time()
        if gcmd.get_command() == 'G28':
            move_end = toolhead.get_last_move_time()
            results = collector.collect_until(move_end)
            samples = load_cell_probe.check_sensor_errors(
                results, self._printer)
            if not samples:
                raise self._printer.command_error(
                    "BDPressure G28 tap found no samples")
            release_check = self._skipped_release_check(samples, 'g28')
            self._apply_probe_travel_info(release_check)
            return epos, release_check, samples
        move_end = toolhead.get_last_move_time()
        results = collector.collect_until(move_end)
        samples = load_cell_probe.check_sensor_errors(results, self._printer)
        if not samples:
            raise self._printer.command_error(
                "BDPressure tap release validation found no trigger samples")
        pre_avg, trigger_raw = self._base_release_check(samples, trigger_time)
        params = self._probe_params_helper.get_probe_params(gcmd)
        retract_dist = params['sample_retract_dist']
        remaining_ratio = self._config_helper.get_release_remaining_ratio(gcmd)
        min_counts = self._config_helper.get_release_min_counts(gcmd)
        release_check = self._build_release_check(
            samples, pre_avg, trigger_raw, None, 0., remaining_ratio)
        self._apply_probe_travel_info(release_check)
        curpos = toolhead.get_position()
        retract_pos = list(curpos)
        retract_start_time = toolhead.get_last_move_time()
        retract_pos[2] += retract_dist
        toolhead.manual_move(retract_pos, params['lift_speed'])
        retract_end_time = toolhead.get_last_move_time()
        results = collector.collect_until(retract_end_time)
        retract_samples = load_cell_probe.check_sensor_errors(
            results, self._printer)
        release_check = self._smooth_release_check(
            samples, retract_samples, pre_avg, trigger_raw, retract_dist,
            retract_start_time, retract_end_time, remaining_ratio)
        samples.extend(retract_samples)
        self._apply_release_min_counts(release_check, min_counts)
        self._apply_probe_travel_info(release_check)
        return epos, release_check, samples

    def _record_tap_attempt(self, epos, release_check, samples):
        self._last_release_check = release_check
        ppa = load_cell_probe.TapAnalysis(samples)
        self._clients.send({'tap': ppa.to_dict(),
                            'release_check': release_check})
        self._is_last_result_valid = release_check['release_valid']
        self._last_result = epos[2]

    def run_tap(self, gcmd):
        self._activate_probe()
        release_retries = self._config_helper.get_release_retries(gcmd)
        attempt = 0
        try:
            while True:
                epos, release_check, samples = self._run_candidate_tap(gcmd)
                release_check['release_attempt'] = attempt + 1
                self._record_tap_attempt(epos, release_check, samples)
                if release_check['release_valid']:
                    return epos, True
                if attempt >= release_retries:
                    break
                attempt += 1
            self._is_last_result_valid = False
            if (not self._is_last_result_valid
                    and self._config_helper.get_require_release_validation(
                        gcmd)):
                raise self._printer.command_error(
                    "BDPressure tap release validation failed")
            return epos, False
        finally:
            self._deactivate_probe()

    def get_status(self, eventtime):
        status = load_cell_probe.TappingMove.get_status(self, eventtime)
        prefix = 'bd_last_tap_'
        for key, value in self._last_release_check.items():
            status[prefix + key] = value
        return status


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


class BDPressureADS1220(load_cell_probe.LoadCellPrinterProbe):
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
        self._mcu = self._load_cell.get_sensor().get_mcu()
        self._mcu_trigger_analog = trigger_analog.MCU_trigger_analog(sensor)
        cmd_queue = self._mcu_trigger_analog.get_dispatch().get_command_queue()
        sos_filter = trigger_analog.MCU_SosFilter(self._mcu, cmd_queue, 4)
        self._mcu_trigger_analog.setup_sos_filter(sos_filter)
        continuous_tare_filter_helper = (
            load_cell_probe.ContinuousTareFilterHelper(
                config, sensor, sos_filter))
        self._param_helper = probe.ProbeParameterHelper(config)
        self._cmd_helper = probe.ProbeCommandHelper(config, self)
        self._probe_offsets = probe.ProbeOffsetsHelper(config)
        load_cell_probing_move = BDPressureProbingMove(
            config, self._load_cell, self._mcu_trigger_analog,
            self._param_helper, continuous_tare_filter_helper, config_helper)
        self._tapping_move = BDPressureTappingMove(
            config, load_cell_probing_move, config_helper,
            self._param_helper, self._load_cell)
        tap_session = BDPressureTapSession(
            config, self._tapping_move, self._probe_offsets,
            self._param_helper)
        self._probe_session = probe.SampleAveragingHelper(
            config, self._param_helper, tap_session.start_probe_session)
        load_cell_probe.LoadCellProbeCommands(config, load_cell_probing_move)
        probe.HomingViaProbeHelper(config, self.get_offsets()[2])
        self._printer.add_object('probe', self)


def load_config(config):
    return BDPressureADS1220(config)
