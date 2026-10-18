# Importing the Celery app here is what makes @shared_task bind to it when Django
# starts, whether the process is the web server, the worker, or a management command.
from core.celery import app as celery_app

__all__ = ("celery_app",)
