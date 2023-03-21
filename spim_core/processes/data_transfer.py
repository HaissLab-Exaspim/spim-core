"""File Transfer process in separate class for Win/Linux compatibility."""
from multiprocessing import Process
from pathlib import Path
import subprocess
import shutil
import os


class DataTransfer(Process):

    def __init__(self, source: Path, dest: Path):
        super().__init__()
        self.source = source
        self.dest = dest

    def run(self):
        """Transfer the file from source to dest."""
        if not self.source.exists():
            raise FileNotFoundError(f"{self.source} does not exist.")
        # Transfer the file.
        print(f"Transferring {self.source} to storage in {self.dest}.")
        if os.name == 'nt':  # Explicitly use xcopy on windows.
            parameters = '" /q /y /i /j /s /e' if os.path.isdir(self.source) else '*" /y /i /j'
            print(f"xcopy {self.source} {self.dest}{parameters}")
            cmd = subprocess.run(f'xcopy "{self.source}" "{self.dest}{parameters}')
            # Delete the old file so we don't run out of local storage.
            print(f"Deleting old file at {self.source}.")
        else:
            if self.source.is_dir():
                shutil.copytree(self.source, self.dest)
            else:
                shutil.copy(self.source, self.dest)
        shutil.rmtree(self.source) if os.path.isdir(self.source) else os.remove(self.source)
        print(f"process finished.")
