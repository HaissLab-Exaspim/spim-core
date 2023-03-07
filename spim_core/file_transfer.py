"""File Transfer process in separate class for Win/Linux compatibility."""
from multiprocessing import Process
from pathlib import Path
import subprocess
import shutil
import os
import time
#import subprocess


class TiffTransfer(Process):

    def __init__(self, source: Path, dest: Path):
        super().__init__()
        self.source = source
        self.dest = dest

    def run(self):
        """Transfer the file from source to dest."""
        if not os.path.isfile(self.source) and not os.path.isdir(self.source):
            raise FileNotFoundError(f"{self.source} does not exist.")
        # Transfer the file.
        # print("SKIPPING FILE TRANSFER TO STORAGE")
        print(f"Transferring {self.source} to storage in {self.dest}.")
        parameters = '" /q /y /i /j /s /e' if os.path.isdir(self.source) else '*" /i /j'
        print(f"xcopy {self.source} {self.dest}{parameters}")
        cmd = subprocess.run(f'xcopy "{self.source}" "{self.dest}{parameters}')
        # Delete the old file so we don't run out of local storage.
        print(f"Deleting old file at {self.source}.")
        shutil.rmtree(self.source) if os.path.isdir(self.source) else os.remove(self.source)
        print(f"process finished.")
