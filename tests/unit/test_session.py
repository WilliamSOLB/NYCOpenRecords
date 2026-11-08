"""Regression checks for the transaction-isolated database fixture."""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Roles
# Import the module so pytest does not register the autouse fixture twice.
from tests import conftest


@pytest.mark.parametrize('iteration', range(2))
def test_commits_do_not_escape_the_test_transaction(db, session, iteration):
    # Reuse the name in separate fixture lifetimes to catch cross-test leaks.
    name = 'fixture-committed-role'
    assert Roles.query.filter_by(name=name).count() == 0
    session.add(Roles(name=name, permissions=0))
    session.commit()
    assert Roles.query.filter_by(name=name).count() == 1
    with db.engine.connect() as observer:
        assert observer.execute(
            select(Roles.id).where(Roles.name == name)
        ).first() is None


def test_rollback_after_integrity_error_keeps_session_usable(db, session):
    session.add(Roles(name='fixture-duplicate-role', permissions=0))
    session.flush()
    session.add(Roles(name='fixture-duplicate-role', permissions=0))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    session.add(Roles(name='fixture-after-rollback', permissions=0))
    session.commit()
    assert Roles.query.filter_by(name='fixture-after-rollback').count() == 1
    with db.engine.connect() as observer:
        assert observer.execute(
            select(Roles.id).where(Roles.name == 'fixture-after-rollback')
        ).first() is None


def test_removed_session_can_be_recreated(session):
    session.add(Roles(name='fixture-before-remove', permissions=0))
    session.flush()
    session.remove()
    assert Roles.query.filter_by(name='fixture-before-remove').count() == 0
    session.add(Roles(name='fixture-after-remove', permissions=0))
    session.commit()
    assert Roles.query.filter_by(name='fixture-after-remove').count() == 1


def test_app_context_teardown_keeps_transaction_isolated(app, db, session):
    # The application enables commit-on-teardown. Its real callback must not
    # commit the outer transaction or leave a removed session unusable.
    assert app.config['SQLALCHEMY_COMMIT_ON_TEARDOWN']
    with app.app_context():
        session.add(Roles(name='fixture-context-teardown', permissions=0))
        session.flush()

    assert Roles.query.filter_by(name='fixture-context-teardown').count() == 1
    session.add(Roles(name='fixture-after-context', permissions=0))
    session.commit()
    with db.engine.connect() as observer:
        assert observer.execute(select(Roles.id).where(
            Roles.name.in_(['fixture-context-teardown', 'fixture-after-context'])
        )).first() is None


@pytest.mark.parametrize('raise_error', [False, True])
def test_fixture_cleanup_restores_session_and_rolls_back(db, raise_error):
    original_session = db.session
    fixture = conftest.session.__wrapped__(db)
    isolated_session = next(fixture)
    connection = isolated_session.get_bind()
    isolated_session.add(Roles(name='fixture-cleanup-role', permissions=0))
    isolated_session.commit()

    if raise_error:
        with pytest.raises(RuntimeError, match='simulated test failure'):
            fixture.throw(RuntimeError('simulated test failure'))
    else:
        with pytest.raises(StopIteration):
            next(fixture)

    assert db.session is original_session
    assert connection.closed
    with db.engine.connect() as observer:
        assert observer.execute(
            select(Roles.id).where(Roles.name == 'fixture-cleanup-role')
        ).first() is None
