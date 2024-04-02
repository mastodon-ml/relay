from __future__ import annotations

import textwrap
import typing

from collections.abc import Callable
from hamlish_jinja import HamlishExtension
from jinja2 import Environment, FileSystemLoader
from jinja2.ext import Extension
from jinja2.nodes import CallBlock
from markdown import Markdown


from . import __version__
from .misc import get_resource

if typing.TYPE_CHECKING:
	from jinja2.nodes import Node
	from jinja2.parser import Parser
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
				HamlishExtension,
				MarkdownExtension
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
		with self.app.database.session(False) as conn:
			config = conn.get_config_all()

		new_context = {
			'view': view,
			'domain': self.app.config.domain,
			'version': __version__,
			'config': config,
			**(context or {})
		}

		return self.get_template(path).render(new_context)


	def render_markdown(self, text: str) -> str:
		return self._render_markdown(text) # type: ignore


class MarkdownExtension(Extension):
	tags = {'markdown'}
	extensions = (
		'attr_list',
		'smarty',
		'tables'
	)


	def __init__(self, environment: Environment):
		Extension.__init__(self, environment)
		self._markdown = Markdown(extensions = MarkdownExtension.extensions)
		environment.extend(
			_render_markdown = self._render_markdown
		)


	def parse(self, parser: Parser) -> Node | list[Node]:
		lineno = next(parser.stream).lineno
		body = parser.parse_statements(
			('name:endmarkdown',),
			drop_needle = True
		)

		output = CallBlock(self.call_method('_render_markdown'), [], [], body)
		return output.set_lineno(lineno)


	def _render_markdown(self, caller: Callable[[], str] | str) -> str:
		text = caller if isinstance(caller, str) else caller()
		return self._markdown.convert(textwrap.dedent(text.strip('\n')))
