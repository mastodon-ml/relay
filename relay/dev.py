import click
import platform
import subprocess
import sys
import time

from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from . import __version__

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
@click.argument('path', required = False, default = 'relay')
@click.option('--strict', '-s', is_flag = True, help = 'Enable strict mode for mypy')
def cli_lint(path: str, strict: bool) -> None:
	cmd: list[str] = [sys.executable, '-m', 'mypy']

	if strict:
		cmd.append('--strict')

	subprocess.run([*cmd, path], check = False)
	subprocess.run([sys.executable, '-m', 'flake8', path])


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

	handler = WatchHandler(dev)
	handler.run_proc()

	watcher = Observer()
	watcher.schedule(handler, str(SCRIPT), recursive=True)
	watcher.start()

	try:
		while True:
			handler.proc.stdin.write(sys.stdin.read().encode('UTF-8'))
			handler.proc.stdin.flush()

	except KeyboardInterrupt:
		pass

	handler.kill_proc()
	watcher.stop()
	watcher.join()



class WatchHandler(PatternMatchingEventHandler):
	patterns = ['*.py']
	cmd = [sys.executable, '-m', 'relay', 'run']


	def __init__(self, dev: bool):
		PatternMatchingEventHandler.__init__(self)

		self.dev: bool = dev
		self.proc = None
		self.last_restart = None


	def kill_proc(self):
		if self.proc.poll() is not None:
			return

		print(f'Terminating process {self.proc.pid}')
		self.proc.terminate()
		sec = 0.0

		while self.proc.poll() is None:
			time.sleep(0.1)
			sec += 0.1

			if sec >= 5:
				print('Failed to terminate. Killing process...')
				self.proc.kill()
				break

		print('Process terminated')


	def run_proc(self, restart=False):
		timestamp = datetime.timestamp(datetime.now())
		self.last_restart = timestamp if not self.last_restart else 0

		if restart and self.proc.pid != '':
			if timestamp - 3 < self.last_restart:
				return

			self.kill_proc()

		if self.dev:
			self.proc = subprocess.Popen([*self.cmd, '-d'], stdin = subprocess.PIPE)

		else:
			self.proc = subprocess.Popen(self.cmd, stdin = subprocess.PIPE)

		self.last_restart = timestamp

		print(f'Started process with PID {self.proc.pid}')


	def on_any_event(self, event):
		if event.event_type not in ['modified', 'created', 'deleted']:
			return

		self.run_proc(restart = True)


if __name__ == '__main__':
	cli()
