"""Screenloop web daemon package."""

import os

APP_NAME = "Screenloop"
APP_AUTHOR = "GezzyDax"
APP_REPOSITORY = "https://github.com/GezzyDax/screenloop"
APP_VERSION = os.environ.get("SCREENLOOP_VERSION", "0.3.0-dev")
APP_REVISION = os.environ.get("SCREENLOOP_REVISION", "")
