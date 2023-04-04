from time import sleep, mktime
from datetime import datetime
import logging


class DictFormatter(logging.Formatter):
    ENTRIES_TO_REMOVE = ['args', 'levelno', 'pathname', 'filename',
                         'module', 'exc_info', 'exc_text', 'stack_info',
                         'funcName', 'msecs', 'relativeCreated',
                         'thread', 'threadName', 'processName', 'process',
                         'lineno']

    def format(self, record):
        pruned_dict = {k:v for k,v in record.__dict__.items()
                       if k not in self.__class__.ENTRIES_TO_REMOVE}
        # Insert the formatted time.
        if self.datefmt:
            time_struct = datetime.fromtimestamp(record.created)
            pruned_dict['created_strftime'] = time_struct.strftime(self.datefmt)
        return repr(pruned_dict)
