"""Spim Base class."""

import pkg_resources
import logging
import shutil
from contextlib import contextmanager
from datetime import date
from functools import wraps
from git import Repo
from logging import Logger, FileHandler, Formatter
from spim_core.operations.dict_formatter import DictFormatter
from math import ceil
from pathlib import Path


def lock_external_user_input(func):
    """Disable any manual hardware user inputs if possible."""
    @wraps(func)
    def inner(self, *args, **kwds):
        # Lock user inputs.
        self.lock_external_user_input()
        try:
            return func(self, *args, **kwds)
        finally:
            # Unlock user inputs.
            self.unlock_external_user_input()
    return inner


class Spim:

    def __init__(self, config_filepath: str, simulated: bool = False):
        """Read config file. Create Mesopim components according to config."""
        # If simulated, no physical connections to hardware should be required.
        # Simulation behavior should be pushed as far down the object
        # hierarchy as possible.
        self.simulated = simulated
        # Setup logging. Application level will add handlers to direct output
        # messages to screen/file/etc.
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.schema_log = logging.getLogger(
            f"{__name__}.{self.__class__.__name__}.schema")
        # Location where images will be saved to from a config-based run.
        # We don't know this in advance since we create the folder at runtime.
        # TODO: consider getting these from the config.
        self.img_storage_dir = None  # folder for image stacks.
        self.deriv_storage_dir = None  # folder for derivative files (MIPs).

        # Config. This will get defined in the child class.
        self.cfg = None

    def log_git_hashes(self):
        """Log the git hashes of this project and all packages."""
        # Iterate through this pkg's required packages and log all git hashes.
        # Warn if they have been changed.
        env = {str(ws): ws.module_path for ws in pkg_resources.working_set if
               ws.module_path and  # This can be None.
               not ws.module_path.endswith(('site-packages', 'dist-packages'))}
        for pkg_name, env_path in env.items():
            repo = Repo(env_path, search_parent_directories=True)
            self.schema_log.debug(f"{pkg_name} on branch {repo.active_branch} at "
                           f"{repo.head.object.hexsha}")
            if repo.is_dirty():
                self.schema_log.error(f"{pkg_name} has uncommitted changes.")

    def log_runtime_estimate(self):
        """Log how much time the configured imaging run will take."""
        raise NotImplementedError

    @contextmanager
    def log_to_file(self, filepath: Path, logger: Logger = None,
                    formatter_class: type[Formatter] = Formatter):
        """Log to a file for the duration of a function's execution.

        :param log_filepath: file name (pathlike) to write the data to.
        :param logger: a particular logger to log to file. If unspecified,
            the root logger will be used.
        """
        log_handler = FileHandler(filepath, 'w')
        log_handler.setLevel(logging.DEBUG)
        # TODO: un-hardcode log format and put it in the config.
        fmt = '%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s'
        fmt = "[SIM] " + fmt if self.simulated else fmt
        datefmt = '%Y-%m-%d,%H:%M:%S.%f'
        log_formatter = formatter_class(fmt, datefmt)
        log_handler.setFormatter(log_formatter)
        if logger is None:  # Get the root logger if no logger was specified.
            logger = logging.getLogger()
        try:
            logger.addHandler(log_handler)
            yield  # Give up control to the decorated function.
        finally:
            log_handler.close()
            logger.removeHandler(log_handler)

    def run(self, overwrite: bool = False):
        """Collect data according to config; populate dest folder with data.

        :param overwrite: bool indicating if we want to overwrite any existing
            data if the output folder already exists. False by default.
        """
        self.cfg.sanity_check()
        # Define img & derivative storage folders if external folder is specified.
        # if external storage directory is not specified, ignore overwrite
        # checks and leave it undefined. Data will be written to local storage
        # folder.
        output_folder = None
        if self.cfg.ext_storage_dir is not None:
            output_folder = \
                self.cfg.ext_storage_dir / Path(self.cfg.subject_id + "-ID_" +
                                                date.today().strftime("%Y_%m_%d"))
            if output_folder.exists() and not overwrite:
                self.log.error(f"Output folder {output_folder.absolute()} exists. "
                               "This function must be rerun with overwrite=True.")
                raise
            self.img_storage_dir = output_folder / Path("micr/")
            self.deriv_storage_dir = output_folder / Path("derivatives/")
            self.log.info(f"Creating datset folder in: {output_folder.absolute()}")
            self.img_storage_dir.mkdir(parents=True, exist_ok=overwrite)
            self.deriv_storage_dir.mkdir(parents=True, exist_ok=overwrite)
            # Save the config file we will run.
            self.cfg.save(output_folder, overwrite=overwrite)
        else:
            self.log.warning("External storage directory unspecified. Files "
                             f"will remain at {self.cfg.local_storage_dir}."
                             f"Any existing files will be overwritten.")
        # Log to a file for the duration of this function's execution.
        # TODO: names should be constants.
        imaging_log_filepath = Path("imaging_log.log")
        schema_log_filepath = Path("schema_log.log")
        try:
            with self.log_to_file(imaging_log_filepath):
                with self.log_to_file(schema_log_filepath, self.schema_log,
                                      DictFormatter):
                    self.log_git_hashes()
                    self.run_from_config()
        finally:  # Transfer log file to output folder, even on failure.
            # Bail early if file does not need to be transferred.
            if output_folder in [Path("."), None]:
                return
            # Note: shutil can't overwrite, so we must delete any prior imaging
            #   log in the destination folder if we are overwriting.
            imaging_log_dest = output_folder/Path(imaging_log_filepath.name)
            if overwrite and imaging_log_dest.exists():
                imaging_log_dest.unlink()
            schema_log_dest = output_folder/Path(schema_log_filepath.name)
            if overwrite and schema_log_dest.exists():
                schema_log_dest.unlink()
            # We must use shutil because we may be moving files across disks.
            shutil.move(str(imaging_log_filepath), str(output_folder))
            shutil.move(str(schema_log_filepath), str(output_folder))

    def get_xy_grid_step(self, tile_overlap_x_percent: float,
                         tile_overlap_y_percent: float):
        """Get the step size (in [um]) for a given x/y tile overlap. """
        # Compute: micrometers per grid step. At 0 tile overlap, this is just
        # the sensor's field of view.
        x_grid_step_um = \
            (1 - tile_overlap_x_percent/100.0) * self.cfg.tile_size_x_um
        y_grid_step_um = \
            (1 - tile_overlap_y_percent/100.0) * self.cfg.tile_size_y_um
        return x_grid_step_um, y_grid_step_um

    def get_tile_counts(self, tile_overlap_x_percent: float,
                        tile_overlap_y_percent: float, z_step_size_um: float,
                        volume_x_um: float, volume_y_um: float, volume_z_um: float):
        """Get the number of x, y, and z tiles for the given x/y tile overlap
        and imaging volume.
        """
        x_grid_step_um, y_grid_step_um = self.get_xy_grid_step(tile_overlap_x_percent,
                                                               tile_overlap_y_percent)
        # Compute step and tile count.
        # Always round up so that we cover the desired imaging region.
        xsteps = ceil((volume_x_um - self.cfg.tile_size_x_um)
                      / x_grid_step_um)
        ysteps = ceil((volume_y_um - self.cfg.tile_size_y_um)
                      / y_grid_step_um)
        zsteps = ceil((volume_z_um - z_step_size_um) / z_step_size_um)
        return 1 + xsteps, 1 + ysteps, 1 + zsteps

    def apply_config(self):
        """Apply the new state (all changes) present in the config object"""
        raise NotImplementedError

    def run_from_config(self):
        raise NotImplementedError("Child class must implement this function.")

    def lock_external_user_input(self):
        raise NotImplementedError

    def unlock_external_user_input(self):
        raise NotImplementedError

    def start_livestream(self, wavelength: int = None):
        raise NotImplementedError

    def stop_livestream(self):
        raise NotImplementedError

    def get_latest_image(self, channel: int = None):
        """Return the most recent acquisition image for display elsewhere."""
        raise NotImplementedError

    def reload_config(self):
        """Reload the toml file."""
        self.cfg.reload()

    def close(self):
        """Safely close all open hardware connections."""
        # Most of the action here should be implemented in a child class that
        # calls super().close() at the very end.
        self.log.info("Ending log.")
