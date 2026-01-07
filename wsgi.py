"""WSGI entry point for production"""
import os
from app import create_app

app = create_app(os.getenv('FLASK_ENV') or 'production')

if __name__ == "__main__":
    app.run()
