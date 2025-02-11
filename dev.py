#!/usr/bin/env python3
import platform
import shutil
import subprocess
import sys
import time

from datetime import datetime, timedelta
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Sequence

try:
	import tomllib

except ImportError:
	if find_spec("toml") is None:
		subprocess.run([sys.executable, "-m", "pip", "install", "toml"])

	import toml as tomllib # type: ignore[no-redef]

if None in [find_spec("click"), find_spec("watchdog")]:
	CMD = [sys.executable, "-m", "pip", "install", "click >= 8.1.0", "watchdog >= 4.0.0"]
	PROC = subprocess.run(CMD, check = False)

	if PROC.returncode != 0:
		sys.exit()

	print("Successfully installed dependencies")

import click

from watchdog.observers import Observer
from watchdog.events import FileSystemEvent, PatternMatchingEventHandler


REPO = Path(__file__).parent
IGNORE_EXT = {
	".py",
	".pyc"
}


@click.group("cli")
def cli() -> None:
	"Useful commands for development"


@cli.command("install")
@click.option("--no-dev", "-d", is_flag = True, help = "Do not install development dependencies")
def cli_install(no_dev: bool) -> None:
	with open("pyproject.toml", "r", encoding = "utf-8") as fd:
		data = tomllib.loads(fd.read())

	deps = data["project"]["dependencies"]
	deps.extend(data["project"]["optional-dependencies"]["dev"])

	subprocess.run([sys.executable, "-m", "pip", "install", "-U", *deps], check = False)


@cli.command("lint")
@click.argument("path", required = False, type = Path, default = REPO.joinpath("relay"))
@click.option("--watch", "-w", is_flag = True,
	help = "Automatically, re-run the linters on source change")
def cli_lint(path: Path, watch: bool) -> None:
	path = path.expanduser().resolve()

	if watch:
		handle_run_watcher([sys.executable, "dev.py", "lint", str(path)], wait = True)
		return

	flake8 = [sys.executable, "-m", "flake8", "dev.py", str(path)]
	mypy = [sys.executable, "-m", "mypy", "--python-version", "3.12", "dev.py", str(path)]

	click.echo("----- flake8 -----")
	subprocess.run(flake8)

	click.echo("\n\n----- mypy -----")
	subprocess.run(mypy)


@cli.command("clean")
def cli_clean() -> None:
	dirs = {
		"dist",
		"build",
		"dist-pypi"
	}

	for directory in dirs:
		shutil.rmtree(directory, ignore_errors = True)

	for path in REPO.glob("*.egg-info"):
		shutil.rmtree(path)

	for path in REPO.glob("*.spec"):
		path.unlink()


@cli.command("build")
def cli_build() -> None:
	from relay import __version__

	with TemporaryDirectory() as tmp:
		arch = "amd64" if sys.maxsize >= 2**32 else "i386"
		cmd = [
			sys.executable, "-m", "PyInstaller",
			"--collect-data", "relay",
			"--hidden-import", "pg8000",
			"--hidden-import", "sqlite3",
			"--name", f"activityrelay-{__version__}-{platform.system().lower()}-{arch}",
			"--workpath", tmp,
			"--onefile", "relay/__main__.py",
		]

		if platform.system() == "Windows":
			cmd.append("--console")

			# putting the spec path on a different drive than the source dir breaks
			if str(REPO)[0] == tmp[0]:
				cmd.extend(["--specpath", tmp])

		else:
			cmd.append("--strip")
			cmd.extend(["--specpath", tmp])

		subprocess.run(cmd, check = False)


@cli.command("run")
@click.option("--dev", "-d", is_flag = True)
def cli_run(dev: bool) -> None:
	print("Starting process watcher")

	cmd = [sys.executable, "-m", "relay", "run"]

	if dev:
		cmd.append("-d")

	handle_run_watcher(cmd, watch_path = REPO.joinpath("relay"))


def handle_run_watcher(
					*commands: Sequence[str],
					watch_path: Path | str = REPO,
					wait: bool = False) -> None:

	handler = WatchHandler(*commands, wait = wait)
	handler.run_procs()

	watcher = Observer()
	watcher.schedule(handler, str(watch_path), recursive=True)
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
	patterns = ["*.py"]


	def __init__(self, *commands: Sequence[str], wait: bool = False) -> None:
		PatternMatchingEventHandler.__init__(self)

		self.commands: Sequence[Sequence[str]] = commands
		self.wait: bool = wait
		self.procs: list[subprocess.Popen[Any]] = []
		self.last_restart: datetime = datetime.now()


	def kill_procs(self) -> None:
		for proc in self.procs:
			if proc.poll() is not None:
				continue

			print(f"Terminating process {proc.pid}")
			proc.terminate()
			sec = 0.0

			while proc.poll() is None:
				time.sleep(0.1)
				sec += 0.1

				if sec >= 5:
					print("Failed to terminate. Killing process...")
					proc.kill()
					break

			print("Process terminated")


	def run_procs(self, restart: bool = False) -> None:
		if restart:
			if datetime.now() - timedelta(seconds = 3) < self.last_restart:
				return

			self.kill_procs()

		self.last_restart = datetime.now()

		if self.wait:
			self.procs = []

			for cmd in self.commands:
				print("Running command:", " ".join(cmd))
				subprocess.run(cmd)

		else:
			self.procs = list(subprocess.Popen(cmd) for cmd in self.commands)
			pids = (str(proc.pid) for proc in self.procs)
			print("Started processes with PIDs:", ", ".join(pids))


	def on_any_event(self, event: FileSystemEvent) -> None:
		if event.event_type not in ["modified", "created", "deleted"]:
			return

		self.run_procs(restart = True)


if __name__ == "__main__":
	cli()
