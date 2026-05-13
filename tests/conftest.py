import os

import django
from django.core.management import call_command
from django.test.utils import setup_databases, teardown_databases

os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "podcast_network.web.settings")
django.setup()


def pytest_sessionstart(session):
    session.config._django_db_config = setup_databases(
        verbosity=0,
        interactive=False,
        keepdb=False,
    )


def pytest_sessionfinish(session, exitstatus):
    db_config = getattr(session.config, "_django_db_config", None)
    if db_config is not None:
        teardown_databases(db_config, verbosity=0)


def pytest_runtest_setup(item):
    call_command("flush", verbosity=0, interactive=False)
