"""Semilla demo: idempotencia, compuerta de la CLI y usuarios por rol."""
import pytest
from app.demo_seed import seed, CASES
from app.extensions import db
from app.infrastructure.models import ProcurementCase, Supplier, User, UserRole
from app.modules.identity.permissions import ROLE_NAMES


@pytest.fixture(scope='module')
def seeded(app):
    with app.app_context():
        first = seed()
        second = seed()
    return first, second


def test_seed_is_idempotent(app, seeded):
    first, second = seeded
    assert len(first['credentials']) == len(ROLE_NAMES)
    assert second['credentials'] == []
    assert second['suppliers_created'] == 0
    with app.app_context():
        assert db.session.query(User).filter(User.username.like('demo-%')).count() == len(ROLE_NAMES)
        assert db.session.query(Supplier).filter(Supplier.code.like('DEMO-PRV-%')).count() == 8
        assert db.session.query(ProcurementCase).filter_by(is_demo=True).count() == len(CASES)
    assert [c['code'] for c in first['cases']] == [c['code'] for c in second['cases']]


def test_every_role_gets_a_demo_user(app, seeded):
    with app.app_context():
        for role in ROLE_NAMES:
            user = db.session.query(User).filter_by(username=f'demo-{role}').one()
            assert user.is_demo and user.must_change_password and user.is_active
            assert db.session.query(UserRole).filter_by(user_id=user.id, role_code=role, revoked_at=None).count() == 1


def test_seed_passwords_are_random_and_not_stored_in_clear(seeded):
    first, _ = seeded
    passwords = [pw for _, pw in first['credentials']]
    assert len(set(passwords)) == len(passwords)
    assert all(len(pw) == 18 for pw in passwords)


def test_cli_rejects_without_allow_demo_seed(app):
    runner = app.test_cli_runner()
    previous = app.config['ALLOW_DEMO_SEED']
    app.config['ALLOW_DEMO_SEED'] = False
    try:
        result = runner.invoke(args=['seed-demo', '--confirm'])
    finally:
        app.config['ALLOW_DEMO_SEED'] = previous
    assert result.exit_code != 0
    assert 'ALLOW_DEMO_SEED' in result.output


def test_cli_requires_confirm(app):
    result = app.test_cli_runner().invoke(args=['seed-demo'])
    assert result.exit_code != 0
    assert '--confirm' in result.output
