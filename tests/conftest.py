import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "podcast_network.web.settings")
django.setup()
