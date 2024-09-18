from __future__ import annotations

import textwrap

from aiohttp.web import Request
from blib import File
from collections.abc import Callable
from hamlish_jinja import HamlishExtension
from jinja2 import Environment, FileSystemLoader
from jinja2.ext import Extension
from jinja2.nodes import CallBlock, Node
from jinja2.parser import Parser
from markdown import Markdown
from typing import TYPE_CHECKING, Any

from . import __version__

if TYPE_CHECKING:
	from .application import Application


class Template(Environment):
	_render_markdown: Callable[[str], str]


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
				File.from_resource('relay', 'frontend'),
				app.config.path.parent.joinpath('template')
			])
		)

		self.app = app
		self.hamlish_enable_div_shortcut = True
		self.hamlish_mode = 'indented'


	def render(self, path: str, request: Request, **context: Any) -> str:
		with self.app.database.session(False) as conn:
			config = conn.get_config_all()

		new_context = {
			'request': request,
			'domain': self.app.config.domain,
			'version': __version__,
			'config': config,
			**(context or {})
		}

		return self.get_template(path).render(new_context)


	def render_markdown(self, text: str) -> str:
		return self._render_markdown(text)


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
