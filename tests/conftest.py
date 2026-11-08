# -*- coding: utf-8 -*-
"""ConfigTest Module

This module handles the setup for running tests agains the OpenRecords application.

.. _Flask Tutorial:
   http://flask.pocoo.org/docs/1.0/tutorial/
"""
import sys
import os
import pytest
from app import create_app, db as _db

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event
from sqlalchemy.orm import scoped_session, sessionmaker

sys.path.append(os.path.join(os.path.dirname(__file__), 'helpers'))


@pytest.yield_fixture(scope='session')
def app():
    """
    Create a session
    Yields:
        app (Flask): Instance of a Flask application

    """
    _app = create_app(config_name='testing')
    ctx = _app.app_context()
    ctx.push()

    yield _app

    ctx.pop()


@pytest.fixture(scope='session')
def client(app: Flask):
    """Retrieve an instance of the Flask test_client.

    .. _Flask Test Client:
        http://flask.pocoo.org/docs/1.0/api/#flask.Flask.test_client

    Args:
        app (Flask): Instance of the Flask application

    Returns:
        app.test_client (Flask.test_client): Returns a client used to test the Flask application
    """
    return app.test_client()


@pytest.yield_fixture(scope='session')
def db(app: Flask):
    """
    Create all of the database tables and yield an instance of the database.
    Args:
        app (Flask): Instance of the flask application.

    Yields:
        db (SQLAlchemy): Instance of the SQLAlchemy DB connector
    """
    _db.app = app
    _db.create_all()

    yield _db

    _db.drop_all()


@pytest.fixture(scope='function', autouse=True)
def session(db: SQLAlchemy):
    """Create a database session to be used for the function.

    Args:
        db (SQLAlchemy): Instance of the SQLAlchemy DB connector

    Yields:
        session_ (SQLAlchemy.session): Session object to be used by the function

    """
    connection = db.engine.connect()
    transaction = connection.begin()
    # Bind SQLAlchemy directly to the connection: Flask-SQLAlchemy 3 routes
    # model queries through db.engines, ignoring a session's default bind.
    factory = sessionmaker(bind=connection, query_cls=db.Query)
    session_ = scoped_session(factory)
    original_session = db.session
    savepoint = connection.begin_nested()

    # Keep application rollback() calls inside the outer test transaction.
    # Listen on the factory so remove() followed by a new session is safe too.
    @event.listens_for(factory, 'after_transaction_end')
    def restart_savepoint(session, ended_transaction):
        nonlocal savepoint
        if not savepoint.is_active:
            savepoint = connection.begin_nested()

    db.session = session_
    try:
        yield session_
    finally:
        event.remove(factory, 'after_transaction_end', restart_savepoint)
        try:
            session_.remove()
        finally:
            db.session = original_session
            try:
                transaction.rollback()
            finally:
                connection.close()
