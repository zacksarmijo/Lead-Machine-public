# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Summit desktop app.

Build command (run from BrowserApp/):
    pyinstaller summit.spec

Output lands in:
    Windows: dist/Summit/
    macOS:   dist/Summit.app/
"""
import os
import sys

REPO = os.path.abspath('.')

# Pick the right icon for the current OS. Fall back to .ico if the
# platform-specific icon is not present (build still succeeds without an icon).
if sys.platform == 'darwin':
    _icon_candidate = os.path.join(REPO, 'summit.icns')
elif sys.platform == 'win32':
    _icon_candidate = os.path.join(REPO, 'summit.ico')
else:
    _icon_candidate = os.path.join(REPO, 'summit.png')

ICON_FILE = _icon_candidate if os.path.exists(_icon_candidate) else None
ICON_DATAS = [(os.path.basename(ICON_FILE), os.path.basename(ICON_FILE))] if ICON_FILE else []

a = Analysis(
    ['desktop_launcher.py'],
    pathex=[
        REPO,
        os.path.join(REPO, 'summit-web'),
        os.path.join(REPO, 'lead-vault'),
        os.path.join(REPO, 'colorado-lead-machine'),
    ],
    # Packages that PyInstaller misses via static analysis
    hiddenimports=[
        # FastAPI / Starlette internals
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        'multipart',                 # python-multipart (FastAPI forms)
        'starlette.templating',
        'jinja2',
        # App modules resolved at runtime via sys.path manipulation
        'shared_schema',
        'trigger_detection',
        'website_audit',
        'lead_vault_store',
        'lead_vault_ai',
        'lead_machine',
        # App routers
        'app.routers.pages',
        'app.routers.dashboard',
        'app.routers.discovery',
        'app.routers.leads',
        'app.routers.ai',
        'app.routers.settings',
        'app.routers.website_monitor',
        'app.website_monitor',
    ],
    datas=[
        # Web assets (templates, static files)
        (os.path.join('summit-web', 'app', 'templates'), os.path.join('summit-web', 'app', 'templates')),
        (os.path.join('summit-web', 'app', 'static'),    os.path.join('summit-web', 'app', 'static')),
        # Sibling Python packages (needed at runtime via sys.path)
        (os.path.join('lead-vault', 'lead_vault_store.py'),       os.path.join('lead-vault', 'lead_vault_store.py')),
        (os.path.join('lead-vault', 'lead_vault_ai.py'),          os.path.join('lead-vault', 'lead_vault_ai.py')),
        (os.path.join('colorado-lead-machine', 'lead_machine.py'),       os.path.join('colorado-lead-machine', 'lead_machine.py')),
        (os.path.join('colorado-lead-machine', 'trigger_detection.py'),  os.path.join('colorado-lead-machine', 'trigger_detection.py')),
        (os.path.join('colorado-lead-machine', 'website_audit.py'),      os.path.join('colorado-lead-machine', 'website_audit.py')),
        ('shared_schema.py', 'shared_schema.py'),
        # Web app Python source (routers, config, etc.)
        (os.path.join('summit-web', 'app'), os.path.join('summit-web', 'app')),
        # App icon (loaded at runtime by pywebview) — platform-specific
        *ICON_DATAS,
    ],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Summit',
    console=False,          # <-- no terminal window
    icon=ICON_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name='Summit',
)

# macOS: also produce a proper .app bundle.
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Summit.app',
        icon=ICON_FILE,
        bundle_identifier='com.summit.app',
    )
