"""Gunicorn configuration for invoice processor"""
import multiprocessing

# Server socket
bind = "0.0.0.0:8000"
backlog = 2048

# Worker processes
workers = 1
worker_class = "sync"
worker_connections = 1000
timeout = 120  # Increased for Claude API processing (default is 30)
keepalive = 2

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "debug"

# Process naming
proc_name = "invoice-processor"

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL (disabled)
keyfile = None
certfile = None
