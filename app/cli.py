import getpass

import click
from flask.cli import with_appcontext

from .extensions import db
from .models import Market, User
from .security import password_problems


def register_cli(app):
    @app.cli.command("init-db")
    @with_appcontext
    def init_db():
        """Create tables (quick start). Use `flask db upgrade` once migrations are initialised."""
        db.create_all()
        click.echo("Tables created.")

    @app.cli.command("create-admin")
    @click.argument("username")
    @with_appcontext
    def create_admin(username):
        """Create the first administrator."""
        username = username.strip().lower()
        if User.query.filter_by(username=username).first():
            raise click.ClickException("That username already exists.")
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            raise click.ClickException("Passwords do not match.")
        problems = password_problems(password)
        if problems:
            raise click.ClickException("Password needs: " + ", ".join(problems))
        user = User(username=username, role="admin", must_change_password=False)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Administrator '{username}' created.")

    @app.cli.command("add-market")
    @click.argument("code")
    @click.argument("name")
    @click.option("--country", default=None)
    @with_appcontext
    def add_market(code, name, country):
        """Add a market, e.g. flask add-market DRC "Vodacom DRC" --country "DR Congo"."""
        code = code.upper()
        if Market.query.filter_by(code=code).first():
            raise click.ClickException("Market already exists.")
        db.session.add(Market(code=code, name=name, country=country))
        db.session.commit()
        click.echo(f"Market {code} added.")

    @app.cli.command("import-excel")
    @click.argument("path", type=click.Path(exists=True, dir_okay=False))
    @click.option("--market", "market_code", required=True, help="Market code, e.g. DRC")
    @with_appcontext
    def import_excel(path, market_code):
        """Import a daily health-check workbook from the command line."""
        import hashlib
        import os

        from .services.importer import import_report
        from .services.parser import ParseError, parse_workbook

        market = Market.query.filter_by(code=market_code.upper()).first()
        if not market:
            raise click.ClickException(f"Unknown market '{market_code}'. Add it with add-market.")
        with open(path, "rb") as handle:
            content = handle.read()
        try:
            parsed = parse_workbook(path)
        except ParseError as exc:
            raise click.ClickException(str(exc))
        batch, found, _ = import_report(parsed, market, "cli", os.path.basename(path),
                                        hashlib.sha256(content).hexdigest())
        db.session.commit()
        for warning in parsed.warnings:
            click.echo(f"warning: {warning}")
        click.echo(f"Imported {batch.metric_rows} days; {len(found)} validation findings.")
