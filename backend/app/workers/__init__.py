"""Celery worker processes that host Arbiter matches.

Nothing here is imported by the API at request time except the Celery
application in ``celery_app``; the heavy task module (which pulls in the
Engine, agents, and sandbox stack) is loaded only inside a worker process.
"""
