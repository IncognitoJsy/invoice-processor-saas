"""Management commands for the application"""
import click
from flask.cli import FlaskGroup
from app import create_app, db

def create_cli_app():
    return create_app()

cli = FlaskGroup(create_app=create_cli_app)

@cli.command()
def init_db():
    """Initialize the database"""
    db.create_all()
    click.echo('Database initialized!')

@cli.command()
def seed_db():
    """Seed the database with sample data"""
    click.echo('Seeding database...')
    # Add your seed logic here
    click.echo('Database seeded!')

if __name__ == '__main__':
    cli()
