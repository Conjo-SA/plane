#!/bin/bash
set -e

python manage.py wait_for_db
# Wait for migrations
python manage.py wait_for_migrations
# Run the processes
# mingle and gossip declare transient non-exclusive queues, which RabbitMQ 4.x
# rejects, so the worker would crash-loop on startup.
celery -A plane worker -l info --without-mingle --without-gossip