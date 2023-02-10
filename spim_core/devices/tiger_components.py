"""Classes for various Mesospim parts, all controlled by an ASI Tigerbox."""

import logging
from time import sleep
from tigerasi.tiger_controller import TigerController, STEPS_PER_UM
from tigerasi.device_codes import ScanPattern, TTLIn0Mode, TTLOut0Mode, \
    RingBufferMode


class FilterWheel:
    """Filter Wheel Abstraction from an ASI Tiger Controller."""

    def __init__(self, tigerbox: TigerController, tiger_axis: int = 1):
        """Constructor.

        :param tigerbox: tigerbox hardware.
        :param tiger_axis: which axis the wheel shows up as according to the
            tigerbox.
        """
        self.tigerbox = tigerbox
        self.tiger_axis = tiger_axis
        self.log = logging.getLogger(__name__ + "." + self.__class__.__name__)

    def get_index(self):
        """return all axes positions as a dict keyed by axis."""
        return self.tigerbox.get_position(str(self.tiger_axis))

    def set_index(self, index: int, wait=True):
        """Set the filterwheel index."""
        cmd_str = f"MP {index}\r\n"
        self.log.debug(f"FW{self.tiger_axis} move to index: {index}.")
        # Note: the filter wheel has slightly different reply line termination.
        self.tigerbox.send("FW 1\r\n", read_until=f"\n\r{self.tiger_axis}>")
        self.tigerbox.send(cmd_str, read_until=f"\n\r{self.tiger_axis}>")
        # TODO: add "busy" check because tigerbox.is_moving() doesn't apply to filter wheels.


class Pose:

    def __init__(self, tigerbox: TigerController, axis_map: dict = None):
        """Connect to hardware.

        :param tigerbox: TigerController instance.
        :param axis_map: dictionary representing the mapping from sample pose
            to tigerbox axis.
            i.e: `axis_map[<sample_frame_axis>] = <tiger_frame_axis>`.
        """
        self.tigerbox = tigerbox
        self.axes = []  # list of strings for this Pose's moveable axes in tiger frame.
        self.log = logging.getLogger(__name__ + "." + self.__class__.__name__)
        # We assume a bijective axis mapping (one-to-one and onto).
        self.sample_to_tiger_axis_map = {}
        self.tiger_to_sample_axis_map = {}
        if axis_map is not None:
            self.log.debug("Remapping axes with the convention "
                           "{'sample frame axis': 'machine frame axis'} "
                           f"from the following dict: {axis_map}.")
            self.sample_to_tiger_axis_map = self._sanitize_axis_map(axis_map)
            r_axis_map =  dict(zip(axis_map.values(), axis_map.keys()))
            self.tiger_to_sample_axis_map = self._sanitize_axis_map(r_axis_map)
            self.log.debug(f"New sample to tiger axis mapping: "
                           f"{self.sample_to_tiger_axis_map}")
            self.log.debug(f"New tiger to sample axis mapping: "
                           f"{self.tiger_to_sample_axis_map}")

    def _sanitize_axis_map(self, axis_map: dict):
        """save an input axis mapping to apply to move commands.

        :param axis_map: dict, where the key (str) is the desired coordinate
            axis and the value (str) is the underlying machine coordinate axis.
            Note that the value may be signed, i.e: '-y'.
        """
        # Move negative signs off keys and onto values.
        sanitized_axis_map = {}
        for axis, t_axis in axis_map.items():
            axis = axis.lower()
            t_axis = t_axis.lower()
            sign = "-" if axis.startswith("-") ^ t_axis.startswith("-") else ""
            sanitized_axis_map[axis.lstrip("-")] = f"{sign}{t_axis.lstrip('-')}"
        return sanitized_axis_map

    def _remap(self, axes: dict, mapping: dict):
        """remap input axes to their corresponding output axes.

        Input axes is the desired coordinate frame convention;
        output axes are the axes as interpreted by the underlying hardware.

        :returns: either: a list of axes remapped to the new names
            or a dict of moves with the keys remapped to the underlying
            underlying hardware axes and the values unchanged.
        """
        new_axes = {}
        for axis, value in axes.items():
            axis = axis.lower()
            # Default to same axis if no remapped axis exists.
            new_axis = mapping.get(axis, axis)  # Get new key.
            negative = 1 if new_axis.startswith('-') else 0
            new_axes[new_axis.lstrip('-')] = (-1)**negative * value # Get new value.
        return new_axes

    def _sample_to_tiger(self, axes: dict):
        return self._remap(axes, self.sample_to_tiger_axis_map)

    def _tiger_to_sample(self, axes: dict):
        return self._remap(axes, self.tiger_to_sample_axis_map)

    def _move_relative(self, wait: bool = True, **axes: float):
        axes_moves = "".join([f'{k}={v:.3f} ' for k, v in axes.items()])
        w_text = "" if wait else "NOT "
        self.log.debug(f"Relative move by: {axes_moves}and {w_text}waiting.")
        # Remap to hardware coordinate frame.
        machine_axes = self._sample_to_tiger(axes)
        self.tigerbox.move_relative(**machine_axes, wait=wait)
        if wait:
            while self.is_moving():
                sleep(0.001)

    def _move_absolute(self, wait: bool = True, **axes: float):
        """Move the specified axes by their corresponding amounts.

        :param wait: If true, wait for the stage to arrive to the specified
            location. If false, (1) do not wait for the chars to exit the
            serial port, (2) do not wait for stage to respond, and
            (3) do not wait for the stage to arrive at the specified location.
        :param axes: dict, keyed by axis of which axis to move and by how much.
        """
        axes_moves = "".join([f'{k}={v:.3f} ' for k, v in axes.items()])
        w_text = "" if wait else "NOT "
        self.log.debug(f"Absolute move to: {axes_moves}and {w_text}waiting.")
        # Remap to hardware coordinate frame.
        machine_axes = self._sample_to_tiger(axes)
        self.tigerbox.move_absolute(**machine_axes, wait=wait)
        if wait:
            while self.is_moving():
                sleep(0.001)

    def get_position(self):
        tiger_position = self.tigerbox.get_position(*self.axes)
        return self._tiger_to_sample(tiger_position)

    def is_moving(self):
        # FIXME: technically, this is true if any tigerbox axis is moving,
        #   but that's all we need for now.
        return self.tigerbox.is_moving()

    def zero_in_place(self, *axes):
        """set the specified axes to zero or all as zero if none specified."""
        # We must populate the axes explicitly since the tigerbox is shared
        # between camera stage and sample stage.
        if len(axes) == 0:
            axes = self.axes
        return self.tigerbox.zero_in_place(*axes)

    def set_axis_backlash(self, **axes: float):
        """Set the axis backlash compensation to a set value (0 to disable)."""
        machine_axes = self._sample_to_tiger(axes)
        self.tigerbox.set_axis_backlash(**machine_axes)

    def setup_finite_tile_scan(self, fast_axis: str, slow_axis: str,
                               fast_axis_start_position: float,
                               slow_axis_start_position: float,
                               slow_axis_stop_position: float,
                               tile_count: int, tile_interval_um: float,
                               line_count: int):
        """Setup a tile scan orchestrated by the device hardware.

        This function sets up the outputting of <tile_count> output pulses
        spaced out by every <tile_interval_um> encoder counts.

        :param fast_axis: the axis to move along to take tile images.
        :param slow_axis: the axis to move across to take tile stacks.
        :param fast_axis_start_position:
        :param slow_axis_start_position:
        :param slow_axis_stop_position:
        :param tile_count: number of TTL pulses to fire.
        :param tile_interval_um: distance to travel between firing TTL pulses.
        :param line_count: number of stacks to collect along the slow axis.
        """
        # TODO: if position is unspecified, we should set is as
        #  "current position" from hardware.
        # Get the axis id in machine coordinate frame.
        machine_fast_axis = self.sample_to_tiger_axis_map[fast_axis.lower()].lstrip("-")
        machine_slow_axis = self.sample_to_tiger_axis_map[slow_axis.lower()].lstrip("-")
        fast_axis_id = self.tigerbox.get_axis_id(machine_fast_axis)
        slow_axis_id = self.tigerbox.get_axis_id(machine_slow_axis)
        # Get encoder divisions in machine coordinate frame.
        ticks_per_mm = self.tigerbox.get_encoder_ticks_per_mm(machine_fast_axis)
        ticks_per_tile = ticks_per_mm * tile_interval_um / 1e3
        ticks_per_tile_rounded = round(ticks_per_tile)
        self.log.debug(f"Requested tile scan {fast_axis}-stack spacing: "
                       f"{tile_interval_um}[um]. "
                       f"Actual spacing: {ticks_per_tile_rounded}[um].")
        # Get start/stop positions in machine coordinate frame.
        machine_fast_axis_start_position = \
            list(self._sample_to_tiger(**{fast_axis: fast_axis_start_position}).items())[0][1]
        machine_slow_axis_start_position = \
            list(self._sample_to_tiger(**{slow_axis: slow_axis_start_position}).items())[0][1]
        machine_slow_axis_stop_position = \
            list(self._sample_to_tiger(**{slow_axis: slow_axis_stop_position}).items())[0][1]
        # Stop any existing scan. Apply machine coordinate frame scan params.
        self.tigerbox.stop_scan()
        self.tigerbox.scan(fast_axis_id=fast_axis_id,
                           slow_axis_id=slow_axis_id,
                           pattern=ScanPattern.RASTER)
        self.tigerbox.scanr(scan_start_mm=machine_fast_axis_start_position,
                            pulse_interval_enc_ticks=ticks_per_tile_rounded,
                            num_pixels=tile_count)
        self.tigerbox.scanv(scan_start_mm=machine_slow_axis_start_position,
                            scan_stop_mm=machine_slow_axis_stop_position,
                            line_count=line_count)

    def start_finite_scan(self):
        """initiate a finite tile scan that has already been setup with
        :meth:`setup_finite_tile_scan`."""
        # Kick off raster-style (default) scan.
        self.tigerbox.start_scan()

    def setup_ext_trigger_linear_move(self, axis: str, num_pts: int,
                                      step_size_mm: float):
        """Setup the stage to do a predefined move when triggered via external
        TTL input.

        :param axis: the lettered axis on which to apply the linear scan.
        :param num_pts: the number of points to visit including the start
            position.
        :param step_size_mm: the spacing between each point along the given
            axis.
        """
        self._setup_relative_ring_buffer_move(axis, step_size_mm)
        #self._setup_array_scan(axis, num_pts, step_size_mm)

    def _setup_relative_ring_buffer_move(self, axis: str, step_size_mm: float):
        """Queue a single-axis relative move of the specified amount."""
        step_size_steps = step_size_mm * 1e3 * STEPS_PER_UM
        tiger_frame_move = self._sample_to_tiger({axis.lower(): step_size_steps})
        hw_scan_axis = self.sample_to_tiger_axis_map[axis.lower()].lower().lstrip("-")

        self.log.debug(f"Provisioning tigerbox for externally triggered "
                       f"relative move: {tiger_frame_move}")
        self.tigerbox.reset_ring_buffer()
        self.tigerbox.setup_ring_buffer(hw_scan_axis, mode=RingBufferMode.TTL)
        self.tigerbox.queue_buffered_move(**tiger_frame_move)
        # TTL mode dictates whether ring buffer move is relative or absolute.
        self.tigerbox.set_ttl_pin_modes(TTLIn0Mode.MOVE_TO_NEXT_REL_POSITION,
                                        TTLOut0Mode.PULSE_AFTER_MOVING,
                                        aux_io_mode=0, aux_io_mask=0,
                                        aux_io_state=0)

    def _setup_array_scan(self, axis: str, num_pts: int,
                          step_size_mm: float, start_pos_mm: float = None):
        self.log.error("This function is untested.")
        # Get Tigerbox axis/direction from args specified in SamplePose frame.
        hw_scan_axis, step_size_mm = \
            next(iter(self._sample_to_tiger({axis.lower(): step_size_mm})))
        _, start_pos_mm = next(iter(self._sample_to_tiger({axis.lower(): start_pos_mm})))
        if hw_scan_axis not in ['x', 'y']:
            raise RuntimeError("Error, Tigerbox 'ARRAY'-style scans can only "
                               "be configured on the x or y stage axes.")
        # Setup scan axis.
        array_kwds = {}
        if hw_scan_axis == 'x':
            array_kwds['x_points'] = num_pts
            array_kwds['delta_x_mm'] = step_size_mm
            array_kwds['x_start_mm'] = start_pos_mm
        elif hw_scan_axis == 'y':
            array_kwds['y_points'] = num_pts
            array_kwds['delta_y_mm'] = step_size_mm
            array_kwds['y_start_mm'] = start_pos_mm
        self.tigerbox.setup_array_scan(**array_kwds)
        # Enable external triggering.
        self.tigerbox.set_ttl_pin_modes(
            TTLIn0Mode.ARRAY_MODE_MOVE_TO_NEXT_POSITION,
            TTLOut0Mode.PULSE_AFTER_MOVING,
            aux_io_mode=0, aux_io_mask=0, aux_io_state=0)
        # Set axis backlash compensation to 0.
        self.tigerbox.set_axis_backlash(**{hw_scan_axis: 0})


class CameraPose(Pose):

    def __init__(self, tigerbox: TigerController, axis_map: dict = None):
        super().__init__(tigerbox, axis_map)
        self.axes = ['N']

    def move_absolute(self, n, wait: bool = True):
        super()._move_absolute(wait, n=n)

    def move_relative(self, n, wait: bool = True):
        axes = {'n': n}
        super()._move_relative(wait, n=n)


class SamplePose(Pose):

    def __init__(self, tigerbox: TigerController, axis_map: dict = None):
        super().__init__(tigerbox, axis_map)
        self.axes = ['X', 'Y', 'Z']

    def move_absolute(self, x=None, y=None, z=None, wait: bool = True):
        # Only specify Non-None axes that we want to move.
        axes = {arg: val for arg, val in locals().items()
                if arg.upper() in self.axes and val is not None}
        super()._move_absolute(wait, **axes)

    def move_relative(self, x=None, y=None, z=None, wait: bool = True):
        # Only specify Non-None axes that we want to move.
        axes = {arg: val for arg, val in locals().items()
                if arg.upper() in self.axes and val is not None}
        super()._move_relative(wait, **axes)
