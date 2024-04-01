import click
import platform
import shutil
import subprocess
import sys
import time

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Sequence

from . import __version__
from . import logger as logging

try:
	from watchdog.observers import Observer
	from watchdog.events import PatternMatchingEventHandler

except ImportError:
	class PatternMatchingEventHandler: # type: ignore
		pass


SCRIPT = Path(__file__).parent
REPO = SCRIPT.parent
IGNORE_EXT = {
	'.py',
	'.pyc'
}


@click.group('cli')
def cli():
	'Useful commands for development'


@cli.command('install')
def cli_install():
	cmd = [
		sys.executable, '-m', 'pip', 'install',
		'-r', 'requirements.txt',
		'-r', 'dev-requirements.txt'
	]

	subprocess.run(cmd, check = False)


@cli.command('lint')
@click.argument('path', required = False, type = Path, default = REPO.joinpath('relay'))
@click.option('--strict', '-s', is_flag = True, help = 'Enable strict mode for mypy')
@click.option('--watch', '-w', is_flag = True,
	help = 'Automatically, re-run the linters on source change')
def cli_lint(path: Path, strict: bool, watch: bool) -> None:
	path = path.expanduser().resolve()

	if watch:
		handle_run_watcher([sys.executable, "-m", "relay.dev", "lint", str(path)], wait = True)
		return

	flake8 = [sys.executable, '-m', 'flake8', str(path)]
	mypy = [sys.executable, '-m', 'mypy', str(path)]

	if strict:
		mypy.append('--strict')

	click.echo('----- flake8 -----')
	subprocess.run(flake8)

	click.echo('\n\n----- mypy -----')
	subprocess.run(mypy)


@cli.command('clean')
def cli_clean():
	dirs = {
		'dist',
		'build',
		'dist-pypi'
	}

	for directory in dirs:
		shutil.rmtree(directory, ignore_errors = True)

	for path in REPO.glob('*.egg-info'):
		shutil.rmtree(path)

	for path in REPO.glob('*.spec'):
		path.unlink()


@cli.command('build')
def cli_build():
	with TemporaryDirectory() as tmp:
		arch = 'amd64' if sys.maxsize >= 2**32 else 'i386'
		cmd = [
			sys.executable, '-m', 'PyInstaller',
			'--collect-data', 'relay',
			'--collect-data', 'aiohttp_swagger',
			'--hidden-import', 'pg8000',
			'--hidden-import', 'sqlite3',
			'--name', f'activityrelay-{__version__}-{platform.system().lower()}-{arch}',
			'--workpath', tmp,
			'--onefile', 'relay/__main__.py',
		]

		if platform.system() == 'Windows':
			cmd.append('--console')

			# putting the spec path on a different drive than the source dir breaks
			if str(SCRIPT)[0] == tmp[0]:
				cmd.extend(['--specpath', tmp])

		else:
			cmd.append('--strip')
			cmd.extend(['--specpath', tmp])

		subprocess.run(cmd, check = False)


@cli.command('run')
@click.option('--dev', '-d', is_flag = True)
def cli_run(dev: bool):
	print('Starting process watcher')

	cmd = [sys.executable, '-m', 'relay', 'run']

	if dev:
		cmd.append('-d')

	handle_run_watcher(cmd)


def handle_run_watcher(*commands: Sequence[str], wait: bool = False):
	handler = WatchHandler(*commands, wait = wait)
	handler.run_procs()

	watcher = Observer()
	watcher.schedule(handler, str(SCRIPT), recursive=True)
	watcher.start()

	try:
		while True:
			time.sleep(1)

	except KeyboardInterrupt:
		pass

	handler.kill_procs()
	watcher.stop()
	watcher.join()



class WatchHandler(PatternMatchingEventHandler):
	patterns = ['*.py']


	def __init__(self, *commands: Sequence[str], wait: bool = False):
		PatternMatchingEventHandler.__init__(self)

		self.commands: Sequence[Sequence[str]] = commands
		self.wait: bool = wait
		self.procs: list[subprocess.Popen] = []
		self.last_restart: datetime = datetime.now()


	def kill_procs(self):
		for proc in self.procs:
			if proc.poll() is not None:
				continue

			logging.info(f'Terminating process {proc.pid}')
			proc.terminate()
			sec = 0.0

			while proc.poll() is None:
				time.sleep(0.1)
				sec += 0.1

				if sec >= 5:
					logging.error('Failed to terminate. Killing process...')
					proc.kill()
					break

			logging.info('Process terminated')


	def run_procs(self, restart: bool = False):
		if restart:
			if datetime.now() - timedelta(seconds = 3) < self.last_restart:
				return

			self.kill_procs()

		self.last_restart = datetime.now()

		if self.wait:
			self.procs = []

			for cmd in self.commands:
				logging.info('Running command: %s', ' '.join(cmd))
				subprocess.run(cmd)

		else:
			self.procs = list(subprocess.Popen(cmd) for cmd in self.commands)
			pids = (str(proc.pid) for proc in self.procs)
			logging.info('Started processes with PIDs: %s', ', '.join(pids))


	def on_any_event(self, event):
		if event.event_type not in ['modified', 'created', 'deleted']:
			return

		self.run_procs(restart = True)


if __name__ == '__main__':
	cli()
