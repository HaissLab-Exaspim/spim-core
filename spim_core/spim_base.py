"""Spim Base class."""

import pkg_resources
import logging
import shutil
from contextlib import contextmanager
from datetime import date
from git import Repo
from pathlib import Path


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
        # logger level must be set to the lowest level of any handler.
        #self.log.setLevel(logging.DEBUG)

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
            repo = Repo(env_path)
            self.log.debug(f"{pkg_name} on branch {repo.active_branch} at "
                           f"{repo.head.object.hexsha}")
            if repo.is_dirty():
                self.log.error(f"{pkg_name} has uncommitted changes.")

    def log_runtime_estimate(self):
        """Log how much time the configured imaging run will take."""
        raise NotImplementedError

    @contextmanager
    def log_to_file(self, log_filepath: Path):
        """Log to a file for the duration of a function's execution."""
        log_handler = logging.FileHandler(log_filepath, 'w')
        log_handler.setLevel(logging.DEBUG)
        # TODO: un-hardcode log format and put it in the config.
        fmt = '%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s'
        fmt = "[SIM] " + fmt if self.simulated else fmt
        datefmt = '%Y-%m-%d,%H:%M:%S'
        log_format = logging.Formatter(fmt, datefmt)
        log_handler.setFormatter(log_format)
        try:
            # Add handler to the root logger.
            logging.getLogger().addHandler(log_handler)
            yield  # Give up control to the decorated function.
        finally:
            log_handler.close()
            logging.getLogger().removeHandler(log_handler)

    def run(self, overwrite: bool = False):
        """Collect data according to config; populate dest folder with data.

        :param overwrite: bool indicating if we want to overwrite any existing
            data if the output folder already exists. False by default.
        """
        self.cfg.sanity_check()
        # Create output folder and folder for storing images.
        output_folder = \
            self.cfg.ext_storage_dir / Path(self.cfg.subject_id + "-ID_" +
                                            date.today().strftime("%Y_%m_%d"))
        if output_folder.exists() and not overwrite:
            self.log.error(f"Output folder {output_folder.absolute()} exists, "
                           "This function must be rerun with overwrite=True.")
            raise
        self.img_storage_dir = output_folder / Path("micr/")
        self.deriv_storage_dir = output_folder / Path("derivatives/")
        self.log.info(f"Creating datset folder in: {output_folder.absolute()}")
        self.img_storage_dir.mkdir(parents=True, exist_ok=overwrite)
        self.deriv_storage_dir.mkdir(parents=True, exist_ok=overwrite)
        # Save the config file we will run.
        self.cfg.save(output_folder, overwrite=overwrite)
        # Log to a file for the duration of this function's execution.
        imaging_log_filepath = Path("imaging_log.log")  # name should be a constant.
        try:
            with self.log_to_file(imaging_log_filepath):
                self.log_git_hashes()
                self.run_from_config()
        finally:  # Transfer log files to output folder, even on failure.
            # Note: shutil can't overwrite, so we must delete any prior imaging
            #   log in the destination folder if we are overwriting.
            imaging_log_dest = output_folder/Path(imaging_log_filepath.name)
            if overwrite and imaging_log_dest.exists():
                imaging_log_dest.unlink()
            # We must use shutil because we may be moving files across disks.
            shutil.move(str(imaging_log_filepath), str(output_folder))

    def run_from_config(self):
        raise NotImplementedError("Child class must implement this function.")

    def livestream(self):
        raise NotImplementedError

    def get_live_view_image(self, channel: int = None):
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
