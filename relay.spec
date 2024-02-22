# -*- mode: python ; coding: utf-8 -*-
import importlib
from pathlib import Path


block_cipher = None
aiohttp_swagger_path = Path(importlib.import_module('aiohttp_swagger').__file__).parent


a = Analysis(
	['relay/__main__.py'],
	pathex=[],
	binaries=[],
	datas=[
		('relay/data', 'relay/data'),
		(aiohttp_swagger_path, 'aiohttp_swagger')
	],
	hiddenimports=[
		'pg8000',
		'sqlite3'
	],
	hookspath=[],
	hooksconfig={},
	runtime_hooks=[],
	excludes=[],
	win_no_prefer_redirects=False,
	win_private_assemblies=False,
	cipher=block_cipher,
	noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
	pyz,
	a.scripts,
	a.binaries,
	a.zipfiles,
	a.datas,
	[],
	name='activityrelay',
	icon=None,
	debug=False,
	bootloader_ignore_signals=False,
	strip=False,
	upx=True,
	upx_exclude=[],
	runtime_tmpdir=None,
	console=True,
	disable_windowed_traceback=False,
	argv_emulation=False,
	target_arch=None,
	codesign_identity=None,
	entitlements_file=None,
)
