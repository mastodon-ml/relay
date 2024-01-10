import logging
import os

from pathlib import Path


LOG_LEVELS = {
	'DEBUG': logging.DEBUG,
	'VERBOSE': 15,
	'INFO': logging.INFO,
	'WARNING': logging.WARNING,
	'ERROR': logging.ERROR,
	'CRITICAL': logging.CRITICAL
}


debug = logging.debug
info = logging.info
warning = logging.warning
error = logging.error
critical = logging.critical


def verbose(message, *args, **kwargs):
	if not logging.root.isEnabledFor(LOG_LEVELS['VERBOSE']):
		return

	logging.log(LOG_LEVELS['VERBOSE'], message, *args, **kwargs)


logging.addLevelName(LOG_LEVELS['VERBOSE'], 'VERBOSE')
env_log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()

try:
	env_log_file = Path(os.environ['LOG_FILE']).expanduser().resolve()

except KeyError:
	env_log_file = None


try:
	log_level = LOG_LEVELS[env_log_level]

except KeyError:
	logging.warning('Invalid log level: %s', env_log_level)
	log_level = logging.INFO


handlers = [logging.StreamHandler()]

if env_log_file:
	handlers.append(logging.FileHandler(env_log_file))

logging.basicConfig(
	level = log_level,
	format = '[%(asctime)s] %(levelname)s: %(message)s',
	handlers = handlers
)
