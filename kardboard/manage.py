from __future__ import absolute_import
from flaskext.script import Manager
from flaskext.celery import install_commands as install_celery_commands

from kardboard import app

manager = Manager(app)
install_celery_commands(manager)

if __name__ == "__main__":
    manager.run()