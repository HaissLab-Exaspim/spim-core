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
from psutil import virtual_memory
import subprocess
import os
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
        self.local_storage_dir = None
        self.img_storage_dir = None  # folder for image stacks.
        self.deriv_storage_dir = None  # folder for derivative files (MIPs).
        self.cache_storage_dir = None # folder for streaming data

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

    def check_ext_disk_space(self, xtiles, ytiles, ztiles):
        """Checks ext disk space before scan to see if disk has enough space scan

        :param xtiles: number of x tiles
        :param ytiles: number of y tiles
        :param ztiles: number of z tiles
        """
        # One tile (tiff) is ~10368 kb
        est_stack_filesize = self.cfg.bytes_per_image * ztiles
        est_scan_filesize = est_stack_filesize*xtiles*ytiles
        if est_scan_filesize >= shutil.disk_usage(self.cfg.ext_storage_dir).free:
            self.log.error("Not enough space in external directory")
            raise

    def check_local_disk_space(self, z_tiles):
        """Checks local disk space before scan to see if disk has enough space for two stacks

           :param z_tiles: number of z tiles
        """

        est_filesize = self.cfg.bytes_per_image * z_tiles
        if est_filesize * 2 >= shutil.disk_usage(self.cfg.local_storage_dir).free:
            self.log.error("Not enough space on disk. Is the recycle bin empty?")
            raise

    def check_read_write_speeds(self, drive: Path):
        """Check local read/write speeds to make sure it can keep up with acquisition

        :param drive: drive you are testing read/write speeds. Usually the local or external storage of instrument
        """

        test_filename = fr"{drive}\test.txt"
        f = open(test_filename, 'a')  # Create empty file to check reading/writing speed
        f.close()
        try:
            speed_MB_s = {}
            for check in ['read', 'write']:
                output = subprocess.check_output(
                    fr'fio --name=test --filename={test_filename} --size=16Gb --rw={check} --bs=1M '
                    r'--direct=1 --numjobs=1 --ioengine=windowsaio --iodepth=1 --runtime=0 --startdelay=0 '
                    r'--thread --group_reporting', shell=True)
                out = str(output)
                speed_MB_s[check] = round(float(out[out.find('BW=') + len('BW='):out.find('MiB/s')])/(10**6/2**20))


            # converting B/s to MB/s
            acq_speed_MB_s = (self.cfg.bytes_per_image*(1/1000000)) * (1/self.cfg.get_period_time())
            # Delete test file
            os.remove(test_filename)

            # Go through both speeds and specify if one or both are the problem
            read_too_slow = False
            write_too_slow = False

            if speed_MB_s['read'] <= acq_speed_MB_s:
                read_too_slow = True
                self.log.warning(f'{drive} read speed too slow')

            if speed_MB_s['write'] <= acq_speed_MB_s:
                write_too_slow = True
                self.log.warning(f'{drive} write speed too slow')

            if read_too_slow or write_too_slow:
                raise
        except subprocess.CalledProcessError:
            self.log.warning('fios not installed on computer. Cannot verify read/write speed')

    def _check_system_memory_resources(self, channel_count: int,
                                       mem_chunk: int):
        """Make sure this machine can image under the specified configuration.

        :param channel_count: the number of channels we want to image with.
        :param mem_chunk: the number of images to hold in one chunk for
            compression
        :raises MemoryError:
        """
        # Calculate double buffer size for all channels.
        bytes_per_gig = (1024 ** 3)
        used_mem_gigabytes = \
            ((self.cfg.bytes_per_image * mem_chunk * 2) / bytes_per_gig) \
            * channel_count
        # TODO: we probably want to throw in 1-2gigs of fudge factor.
        free_mem_gigabytes = virtual_memory()[1] / bytes_per_gig
        if free_mem_gigabytes < used_mem_gigabytes:
            raise MemoryError("System does not have enough memory to run "
                              "the specified number of channels. "
                              f"{used_mem_gigabytes:.1f}[GB] are required but "
                              f"{free_mem_gigabytes:.1f}[GB] are available.")

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
        if self.cfg.local_storage_dir is not None and self.cfg.ext_storage_dir != self.cfg.local_storage_dir:
            self.cache_storage_dir = \
                self.cfg.local_storage_dir / Path(self.cfg.subject_id + "-ID_" + date_time_string)
            if self.cache_storage_dir.exists() and not overwrite:
                self.log.error(f"Local folder {self.cache_storage_dir.absolute()} exists. "
                               "This function must be rerun with overwrite=True.")
                raise
            self.log.info(f"Creating dataset folder in: {self.cache_storage_dir.absolute()}")
            self.cache_storage_dir.mkdir(parents=True, exist_ok=overwrite)
            self.local_storage_dir = self.cache_storage_dir
        output_folder = None
        if self.cfg.ext_storage_dir is not None and self.cfg.ext_storage_dir != self.cfg.local_storage_dir:
            output_folder = \
                self.cfg.ext_storage_dir / Path(self.cfg.subject_id + "-ID_" + date_time_string)
            if output_folder.exists() and not overwrite:
                self.log.error(f"Output folder {output_folder.absolute()} exists. "
                               "This function must be rerun with overwrite=True.")
                raise
            self.img_storage_dir = output_folder / Path("micr/")
            self.deriv_storage_dir = output_folder / Path("derivatives/")
            self.log.info(f"Creating dataset folder in: {output_folder.absolute()}")
            self.img_storage_dir.mkdir(parents=True, exist_ok=overwrite)
            self.deriv_storage_dir.mkdir(parents=True, exist_ok=overwrite)
            # Save the config file we will run.
            self.cfg.save(output_folder, overwrite=overwrite)

        if self.cfg.ext_storage_dir == self.cfg.local_storage_dir:
            self.log.warning("External and local storage directories are the same. Files "
                             f"will remain at {self.cfg.local_storage_dir}.")

            output_folder = self.cfg.local_storage_dir / Path(self.cfg.subject_id + "-ID_" + date_time_string)
            self.img_storage_dir = None
            self.local_storage_dir = output_folder / Path("micr/")
            self.deriv_storage_dir = output_folder / Path("derivatives/")
            self.log.info(f"Creating dataset folder in: {output_folder.absolute()}")
            self.local_storage_dir.mkdir(parents=True, exist_ok=overwrite)
            self.deriv_storage_dir.mkdir(parents=True, exist_ok=overwrite)
            # Save the config file we will run.
            self.cfg.save(output_folder, overwrite=overwrite)


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
