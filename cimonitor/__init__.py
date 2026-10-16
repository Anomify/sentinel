"""Sentinel, GTM-stack & competitive intelligence."""
__version__ = "2.0.0"

from . import envfile as _envfile

_envfile.load()  # pick up ./.env before anything reads os.environ
