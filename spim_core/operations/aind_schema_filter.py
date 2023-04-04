import logging


class AINDSchemaFilter(logging.Filter):

    def filter(self, record):
        """Returns True for a record that matches a log we want to keep."""
        return 'schema' in record.__dict__.get('tags', [])
