"""File Transfer process in separate class for Win/Linux compatibility."""
from multiprocessing import Process
from pathlib import Path
import subprocess
import shutil
import os
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
        parameters = ' /i /j /s /e /t' if os.path.isdir(self.source) else '* /i /j'
        cmd = subprocess.Popen(f"xcopy {self.source} {self.dest}{parameters}")
        #shutil.copy2(self.source, self.dest)
        # Delete the old file so we don't run out of local storage.
        while cmd.poll() is None:
            # Stalls deleting files until all are copied over
            not_finished = 'Not finished copying file'
        print(f"Deleting old file at {self.source}.")
        shutil.rmtree(self.source) if os.path.isdir(self.source) else os.remove(self.source)
        print(f"process finished.")
