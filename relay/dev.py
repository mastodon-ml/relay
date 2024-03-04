import click
import subprocess
import sys
import time

from datetime import datetime
from pathlib import Path

try:
	from watchdog.observers import Observer
	from watchdog.events import PatternMatchingEventHandler

except ImportError:
	class PatternMatchingEventHandler:
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
def cli_lint(path):
	subprocess.run([sys.executable, '-m', 'flake8', path], check = False)
	subprocess.run([sys.executable, '-m', 'pylint', path], check = False)


@cli.command('manifest-gen')
def cli_manifest_install():
	paths = []

	for path in SCRIPT.rglob('*'):
		if path.suffix.lower() in IGNORE_EXT or not path.is_file():
			continue

		paths.append(path)

	with REPO.joinpath('MANIFEST.in').open('w', encoding = 'utf-8') as fd:
		for path in paths:
			fd.write(f'include {str(path.relative_to(SCRIPT))}\n')


@cli.command('build')
def cli_build():
	cmd = [sys.executable, '-m', 'PyInstaller', 'relay.spec']
	subprocess.run(cmd, check = False)


@cli.command('run')
def cli_run():
	print('Starting process watcher')

	handler = WatchHandler()
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
	cmd = [sys.executable, '-m', 'relay', 'run', '-d']


	def __init__(self):
		PatternMatchingEventHandler.__init__(self)

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

		# pylint: disable=consider-using-with
		self.proc = subprocess.Popen(self.cmd, stdin = subprocess.PIPE)
		self.last_restart = timestamp

		print(f'Started process with PID {self.proc.pid}')


	def on_any_event(self, event):
		if event.event_type not in ['modified', 'created', 'deleted']:
			return

		print(event.src_path)
		self.run_proc(restart = True)


if __name__ == '__main__':
	cli()
