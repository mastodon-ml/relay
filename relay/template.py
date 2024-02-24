from __future__ import annotations

import typing

from hamlish_jinja.extension import HamlishExtension
from jinja2 import Environment, FileSystemLoader

from pathlib import Path

from .database.config import THEMES
from .misc import get_resource

if typing.TYPE_CHECKING:
	from typing import Any
	from .application import Application
	from .views.base import View


class Template(Environment):
	def __init__(self, app: Application):
		Environment.__init__(self,
			autoescape = True,
			trim_blocks = True,
			lstrip_blocks = True,
			extensions = [
				HamlishExtension
			],
			loader = FileSystemLoader([
				get_resource('frontend'),
				app.config.path.parent.joinpath('template')
			])
		)

		self.app = app
		self.hamlish_enable_div_shortcut = True
		self.hamlish_mode = 'indented'


	def render(self, path: str, view: View | None = None, **context: Any) -> str:
		with self.app.database.session(False) as s:
			config = s.get_config_all()

		new_context = {
			'view': view,
			'domain': self.app.config.domain,
			'config': config,
			'theme': THEMES.get(config['theme'], THEMES['default']),
			**(context or {})
		}

		return self.get_template(path).render(new_context)
