"""TOML wrapper that enables edits, reloads, and manages derived params."""

import toml
import logging
from pathlib import Path
from typing import Union, List
from numpy import dtype


class TomlConfig:

    def __init__(self, toml_filepath: Union[str, None] = None,
                 config_template: Union[dict, None] = None,
                 create: bool = False):
        """Load an existing config or create one from the specified template.

            :param toml_filepath: location of the config if we are
                loading one from file. Default location to save to. Optional.
            :param config_template: dict with the same key structure
                as the TOML file. Optional. Only required if `create` is True.
            :param create: if True, create a config object from the specified
                `config_template`.
        """
        self.cfg = None
        self.path = Path(toml_filepath) if toml_filepath else None
        self.template = config_template
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        # User specified existing config.
        if self.path and self.path.exists():
            self.log.info(f"Loading: {self.path.resolve()}")
            self.load(self.path)
        # User specified existing config but it does not exist.
        elif self.path and not self.path.exists() and not create:
            raise ValueError(f"Configuration file at "
                             f"{str(self.path.absolute())} does not exist.")
        # User specified create new config at specified path.
        elif self.path and config_template and create:
            self.log.info(f"Creating: {self.path.resolve()} from template.")
            self.load_from_template()
        # No config specified; not creating.
        else:
            raise ValueError("No configuration was specified.")
        self.doc_name = self.path.name

    def load_from_template(self, config_template: dict = None):
        """Create a config from a template if one was specified on __init__.

        .. code-block:: python

            cfg.load_from_template() # Optional dict may be passed in if one was
                                     # not specified in the init.
            cfg.save("./config.toml")  # Save the config made from the template.

        """
        if config_template:
            self.template = config_template
        if self.template is None:
            raise ValueError("Error: No template was specified from which to "
                             "create the configuration.")
        # This will destroy anything that we loaded.
        self.cfg = toml.loads(toml.dumps(self.template))

    def load(self, filepath: Path = None):
        """Load a config from file specified in filepath or __init__."""
        if filepath:
            self.path = filepath
        assert (self.path.is_file() and self.path.exists()), \
            f"Error: config does not exist at provided filepath: {self.path}."
        with open(filepath, 'r') as toml_file:
            self.cfg = toml.load(toml_file)
        self.doc_name = self.path.name
        if not self.template:
            return
        # TODO: template comparison. possibly with deepdiff.
        #  https://github.com/seperman/deepdiff

    def reload(self):
        """Reload the config from the file we loaded the config from.

        Take all the new changes.
        """
        # This will error out if the config never existed in the first place.
        self.load(self.path)

    def save(self, filepath: str = None, overwrite: bool = True):
        """Save config to specified file, or overwrite if no file specified.

        :param filepath: can be a path to a folder or a file.
            If folder, we use the original filename (or default filename
            if filename never specified).
            If file, we use the specified filename.
            If no path specified, we overwrite unless flagged not to do so.
        :param overwrite: bool to indicate if we overwrite an existing file.
            Defaults to True so that we can save() over a previous file.
        """
        # if filepath unspecified, overwrite the original.
        write_path = Path(filepath) if filepath else self.path
        # if file name is unspecified, use the original.
        if write_path.is_dir():
            write_path = write_path / self.doc_name
        with write_path.open("w") as f:
            f.write(toml.dumps(self.cfg))


class SpimConfig(TomlConfig):

    def __init__(self, toml_filepath: Union[str, None] = None,
                 config_template: Union[dict, None] = None,
                 create: bool = False):
        super().__init__(toml_filepath, config_template, create=create)

        # Note: these are mutable, so reloading the toml doesn't affect them.
        self.imaging_specs = self.cfg['imaging_specs']
        self.design_specs = self.cfg['design_specs']
        self.tile_specs = self.cfg['tile_specs']

    def sanity_check(self):
        """Confirm that config fields have values that are in the right ranges.
        """
        # Note: do not check if fields exist. Check whether fields are
        #   the right ranges.
        # TODO: validate config to ensure all fields exist elsewhere.
        # Log all errors, but raise an AssertionError at the end if
        # any failures exist.
        error_msgs = []
        # Check if there is at least one laser wavelength to image with.
        if len(self.channels) < 1:
            msg = "At least one laser must be specified to image with."
            self.log.error(msg)
            error_msgs.append(msg)
        # Check that laser wavelengths we want to image with actually exist.
        for channel in self.channels:
            if channel not in self.possible_channels:
                msg = f"{channel}[nm] wavelength is not configured for imaging."
                self.log.error(msg)
                error_msgs.append(msg)
        # TODO: Check that a valid file transfer protocol is specified.
        # Warn if there are repeat values in imaging wavelengths.
        if len(set(self.channels)) > len(self.channels):
            self.log.warning("Repeat values are present in the sequence of "
                             "lasers to image with.")
        # Check if z voxel size was user-specified as different from isotropic.
        # Pull this manually rather than using the @property so we don't get
        # the xy fallback value.
        z_step_size_um = self.cfg['imaging_specs'].get('z_step_size_um', None)
        if z_step_size_um is None:
            self.log.warning("Z Step Size not listed. Defaulting to an "
                             f"isotropic step size of {self.x_voxel_size_um}")
        # Warn on no external storage dir.
        if self.ext_storage_dir == self.local_storage_dir:
            self.log.warning("Output storage directory unspecified. Data will "
                             f"be saved to {self.ext_storage_dir.resolve()}.")
        # TODO: Throw error on out-of-bounds stage x, y, or z movement.
        # TODO: finish refactor.
        assert 0 < self.tile_overlap_x_percent < 100, \
            f"Error: Specified x overlap ({self.tile_overlap_x_percent}) " \
            "is out of bounds."
        assert 0 < self.tile_overlap_y_percent < 100, \
            f"Error: Specified x overlap ({self.tile_overlap_x_percent}) " \
            "is out of bounds."

        # Create a big error message at the end.
        if len(error_msgs):
            all_msgs = "\n".join(error_msgs)
            raise AssertionError(all_msgs)

    # Make @Properties to simplify structure of the toml file
    @property
    def channels(self):
        """Returns the ordered list of laser wavelengths used just for imaging.

        Note: this may be a subset of all configured wavelengths.
        Note: repeats are allowed since this list is interpretted as an
            execution order, but it is rare.
        """
        return [int(c) for c in self.cfg['imaging_specs']['laser_wavelengths']]

    @channels.setter
    def channels(self, wavelengths: List[int]):
        self.cfg['imaging_specs']['laser_wavelengths'] = wavelengths
        
    @property
    def possible_channels(self):
        """Returns the set of all machine-configured laser wavelengths.

        Note: this set represents all channels that the machine has been
        provisioned to image with. It is not the subset of wavelengths used for
        imaging. Use :meth:`channels` for just the channels used for imaging.
        """
        return [int(nm) for nm in self.cfg['channel_specs'].keys()]

    @property
    def subject_id(self):
        return self.imaging_specs['subject_id']

    @subject_id.setter
    def subject_id(self, val: str):
        self.imaging_specs['subject_id'] = val

    @property
    def volume_x_um(self):
        return self.imaging_specs['volume_x_um']

    @volume_x_um.setter
    def volume_x_um(self, vol: float):
        self.imaging_specs['volume_x_um'] = vol

    @property
    def volume_y_um(self):
        return self.imaging_specs['volume_y_um']

    @volume_y_um.setter
    def volume_y_um(self, vol: float):
        self.imaging_specs['volume_y_um'] = vol

    @property
    def volume_z_um(self):
        return self.imaging_specs['volume_z_um']

    @volume_z_um.setter
    def volume_z_um(self, vol: float):
        self.imaging_specs['volume_z_um'] = vol
        
    @property
    def sensor_row_count(self):
        return self.tile_specs['row_count_pixels']

    @sensor_row_count.setter
    def sensor_row_count(self, row_count):
        self.design_specs['row_count_pixels'] = row_count
    
    @property
    def sensor_column_count(self):
        return self.tile_specs['column_count_pixels']

    @sensor_column_count.setter
    def sensor_column_count(self, column_count):
        self.design_specs['column_count_pixels'] = column_count

    @property
    def tile_prefix(self):
        return self.imaging_specs['tile_prefix']

    @tile_prefix.setter
    def tile_prefix(self, val: str):
        self.imaging_specs['tile_prefix'] = val

    @property
    def tile_size_x_um(self):
        """The number of microns along the X angle field of view."""
        return float(self.tile_specs['x_field_of_view_um'])

    @tile_size_x_um.setter
    def tile_size_x_um(self, micrometers: float):
        self.tile_specs['x_field_of_view_um'] = micrometers

    @property
    def tile_size_y_um(self):
        """The number of microns along the Y angle field of view."""
        return float(self.tile_specs['y_field_of_view_um'])

    @tile_size_y_um.setter
    def tile_size_y_um(self, micrometers: float):
        self.tile_specs['y_field_of_view_um'] = micrometers

    @property
    def tile_overlap_x_percent(self):
        return self.imaging_specs['tile_overlap_x_percent']

    @tile_overlap_x_percent.setter
    def tile_overlap_x_percent(self, percent: float):
        self.imaging_specs['tile_overlap_x_percent'] = percent

    @property
    def tile_overlap_y_percent(self):
        return self.imaging_specs['tile_overlap_y_percent']

    @tile_overlap_y_percent.setter
    def tile_overlap_y_percent(self, percent: float):
        self.imaging_specs['tile_overlap_y_percent'] = percent
        
    @property
    def local_storage_dir(self) -> Path:
        """returns the config-specified external storage directory."""
        return Path(self.cfg['imaging_specs']['local_storage_directory'])

    @local_storage_dir.setter
    def local_storage_dir(self, storage_path: Path):
        """Save the local storage directory to the live config object."""
        self.cfg['imaging_specs']['local_storage_directory'] = \
            str(storage_path.absolute())

    @property
    def ext_storage_dir(self) -> Path:
        """returns the config-specified external storage directory.
        If unspecified, default to the local storage directory.
        """
        try:
            return Path(self.cfg['imaging_specs']['external_storage_directory'])
        except KeyError:
            self.cfg['imaging_specs']['external_storage_directory'] = \
                str(self.local_storage_dir)  # This is already a Path object.
            return self.ext_storage_dir  # Recurse but successfully this time.

    @ext_storage_dir.setter
    def ext_storage_dir(self, storage_path: Path):
        """Save the external storage directory to the live config object."""
        self.cfg['imaging_specs']['external_storage_directory'] = \
            str(storage_path.absolute())

    @property
    def image_dtype(self):
        """returns the datatype of the tile as a numpy dtype object."""
        return dtype(self.tile_specs['data_type'])

    @image_dtype.setter
    def image_dtype(self, data_type: str):
        """Sets the tile dtype as a string."""
        self.tile_specs['data_type'] = data_type

    # FIXME: remove and use sensor_row_count
    @property
    def row_count_px(self):
        """returns the number of pixels in a tile row."""
        return self.tile_specs['row_count_pixels']

    @row_count_px.setter
    def row_count_px(self, pixels: int):
        self.tile_specs['row_count_pixels'] = pixels

    # FIXME: remove and use sensor_column_count
    @property
    def column_count_px(self):
        """returns the number of pixels in a tile column."""
        return self.tile_specs['column_count_pixels']

    @column_count_px.setter
    def column_count_px(self, pixels: int):
        self.tile_specs['column_count_pixels'] = pixels

# Derived parameters. Note that these do not have setters.
    @property
    def bytes_per_image(self):
        return self.row_count_px * self.column_count_px \
               * self.image_dtype.itemsize

    @property
    def x_voxel_size_um(self):
        return self.tile_size_x_um / self.sensor_column_count

    @property
    def y_voxel_size_um(self):
        return self.tile_size_y_um / self.sensor_row_count

    @property
    def z_step_size_um(self):
        """z step size in micrometers; analagous to a z voxel size."""
        # Note: x and y pixel lengths are the same, but this is not generally
        #   the case.
        return self.cfg['imaging_specs'].get('z_step_size_um',
                                             self.x_voxel_size_um)

    @z_step_size_um.setter
    def z_step_size_um(self, um: float):
        self.cfg['imaging_specs']['z_step_size_um'] = um
