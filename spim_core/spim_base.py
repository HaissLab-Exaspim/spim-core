"""Spim Base class."""
import pkgutil
import logging
import shutil
from contextlib import contextmanager
import datetime
from functools import wraps
from pygit2 import Repository, GitError
from logging import Logger, FileHandler, Formatter, Filter
from pygit2 import Repository
from logging import Logger, FileHandler, Formatter
from spim_core.operations.dict_formatter import DictFormatter
from spim_core.operations.aind_schema_filter import AINDSchemaFilter
from math import ceil
from pathlib import Path
from typing import Union


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
        # We don't know the following folder paths in advance since we create
        # the top folder at runtime based on current date/time.
        self.cache_storage_dir = None  # temp folder for holding image stacks.
        self.img_storage_dir = None  # destination folder for all image stacks.
        self.deriv_storage_dir = None  # destination folder for derivative
                                       # files (MIPs).
        # Config. This will get defined in the child class.
        self.cfg = None

    def log_git_hashes(self):
        """Log the git hashes of this project and all packages."""
        # Iterate through this pkg's packages installed in editable mode and
        # log all git hashes.
        # Scoop up packages installed in editable mode.
        env = {name: info.path for info, name, is_pkg in pkgutil.iter_modules()
               if is_pkg and
               not info.path.endswith(('site-packages', 'dist_packages',
                                       'lib-dynload', # lib-dynload for unix.
                                       'lib'))  # lib for windows.
               and not info.path.rsplit("/", 1)[-1].startswith('python')}
        for pkg_name, env_path in env.items():
            #print(pkg_name, env_path)
            try:
                repo = Repository(env_path)  # will search parent directories
                self.schema_log.debug(f"{pkg_name} on branch {repo.head.name} at "
                                      f"{repo.head.target}")
                # Log dirty repositories.
                if repo.status(untracked_files="no"):  # ignore untracked files.
                    self.schema_log.error(f"{pkg_name} has uncommitted changes.")
            except GitError:
                self.log.error(f"Could not record git hash of {pkg_name}.")

    def log_runtime_estimate(self):
        """Log how much time the configured imaging run will take."""
        raise NotImplementedError

    @contextmanager
    def log_to_file(self, filepath: Path, logger: Logger = None,
                    formatter_class: type[Formatter] = Formatter,
                    filter_class: Union[type[Filter], None] = None):
        """Log to a file for the duration of a function's execution.

        :param log_filepath: file name (pathlike) to write the data to.
        :param logger: a particular logger to log to file. If unspecified,
            the root logger will be used.
        :param formatter_class: the formatter class type to instantiate.
        :param filter_class: the filter class type to instantiate.
        """
        log_handler = FileHandler(filepath, 'w')
        log_handler.setLevel(logging.DEBUG)
        # TODO: un-hardcode log format and put it in the config.
        fmt = '%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s'
        fmt = "[SIM] " + fmt if self.simulated else fmt
        datefmt = '%Y-%m-%d,%H:%M:%S'
        log_formatter = formatter_class(fmt, datefmt)
        log_handler.setFormatter(log_formatter)
        if filter_class:
            log_handler.addFilter(filter_class())
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
        date_time_string = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        # Assume self.cfg.local_storage_dir exists if we passed sanity check.
        top_folder_name = Path(self.cfg.subject_id + "-ID_" + date_time_string)
        # Create required local folder structure.
        local_storage_dir = self.cfg.local_storage_dir / top_folder_name
        if local_storage_dir.exists() and not overwrite:
            self.log.error(f"Local folder {local_storage_dir.absolute()} exists. "
                           "This function must be rerun with overwrite=True.")
            raise
        # Create cache subfolder.
        self.cache_storage_dir = local_storage_dir / Path("micr/")
        self.log.info(f"Creating cache dataset folder in: "
                      f"{self.cache_storage_dir.absolute()}")
        self.cache_storage_dir.mkdir(parents=True, exist_ok=overwrite)
        # Create required external folder structure.
        output_dir = None
        if self.cfg.ext_storage_dir is None:
            output_dir = local_storage_dir
        elif self.cfg.local_storage_dir == self.cfg.ext_storage_dir:
            output_dir = local_storage_dir
        else:
            output_dir = self.cfg.ext_storage_dir / top_folder_name
            if output_dir.exists() and not overwrite:
                self.log.error(f"Output folder {output_dir.absolute()} exists. "
                               "This function must be rerun with overwrite=True.")
                raise
        self.log.info(f"Creating dataset folder in: {output_dir.absolute()}")
        self.img_storage_dir = output_dir / Path("micr/")
        self.deriv_storage_dir = output_dir / Path("derivatives/")
        self.img_storage_dir.mkdir(parents=True, exist_ok=overwrite)
        self.deriv_storage_dir.mkdir(parents=True, exist_ok=overwrite)
        # Save the config file we will run to the destination directory.
        self.cfg.save(output_dir, overwrite=overwrite)

        # Log to a file for the duration of this function's execution.
        # TODO: names should be constants.
        imaging_log_filepath = Path("imaging_log.log")
        schema_log_filepath = Path("schema_log.log")
        try:
            with self.log_to_file(imaging_log_filepath):
                # Create log file from which to generate the AIND schema.
                with self.log_to_file(schema_log_filepath, None,
                                      DictFormatter, AINDSchemaFilter):
                    self.log_git_hashes()
                    self.run_from_config()
        finally:  # Transfer log file to output folder, even on failure.
            # Bail early if file does not need to be transferred.
            if output_dir in [Path("."), None]:
                return
            # Note: shutil can't overwrite, so we must delete any prior imaging
            #   log in the destination folder if we are overwriting.
            imaging_log_dest = output_dir/Path(imaging_log_filepath.name)
            if overwrite and imaging_log_dest.exists():
                imaging_log_dest.unlink()
            schema_log_dest = output_dir/Path(schema_log_filepath.name)
            if overwrite and schema_log_dest.exists():
                schema_log_dest.unlink()
            # We must use shutil because we may be moving files across disks.
            shutil.move(str(imaging_log_filepath), str(output_dir))
            shutil.move(str(schema_log_filepath), str(output_dir))

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
