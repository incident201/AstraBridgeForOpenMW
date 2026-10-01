import logging
import os
from pathlib import Path

from aiohttp import web
from .runtime import Runtime
from .server import application


def main():
    installation=Path(os.environ.get('ASTRA_INSTALLATION','/opt/astrabridge'))
    storage=Path(os.environ.get('ASTRA_STORAGE','/data'))
    game=Path(os.environ.get('ASTRA_GAME','/managed-game/content'))
    logging.basicConfig(level=logging.INFO,handlers=[logging.StreamHandler()])
    runtime=Runtime(installation,storage,game)
    runtime.profile_logging()
    web.run_app(application(runtime,os.environ.get('ASTRA_API_TOKEN','')),
                host='0.0.0.0',port=int(os.environ.get('ASTRA_API_PORT','18770')),access_log=None,shutdown_timeout=120)


if __name__=='__main__':main()
