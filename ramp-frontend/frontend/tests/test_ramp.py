import shutil

import pytest

from ramputils import generate_flask_config
from ramputils import read_config
from ramputils.testing import path_config_example

from rampdb.model import Model
from rampdb.testing import create_toy_db
from rampdb.utils import setup_db
from rampdb.utils import session_scope

from rampdb.tools.event import get_event
from rampdb.tools.user import add_user
from rampdb.tools.team import get_event_team_by_name

from frontend import create_app
from frontend.testing import login_scope


@pytest.fixture(scope='module')
def database_config():
    return read_config(path_config_example(), filter_section='sqlalchemy')


@pytest.fixture(scope='module')
def config():
    return read_config(path_config_example())


@pytest.fixture(scope='module')
def client_session(config):
    try:
        create_toy_db(config)
        flask_config = generate_flask_config(config)
        app = create_app(flask_config)
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        with session_scope(config['sqlalchemy']) as session:
            yield app.test_client(), session
    finally:
        shutil.rmtree(config['ramp']['deployment_dir'], ignore_errors=True)
        # In case of failure we should close the global flask engine
        from frontend import db as db_flask
        db_flask.session.close()
        db, Session = setup_db(config['sqlalchemy'])
        Model.metadata.drop_all(db)


@pytest.mark.parametrize(
    "page",
    ["/events/iris_test",
     "/events/iris_test/sign_up",
     "/events/iris_test/sandbox",
     "/credit/xxx",
     "/event_plots/iris_test"]
)
def test_check_login_required(client_session, page):
    client, _ = client_session

    rv = client.get(page)
    assert rv.status_code == 302
    assert 'http://localhost/login' in rv.location
    rv = client.get(page, follow_redirects=True)
    assert rv.status_code == 200


@pytest.mark.parametrize(
    "page",
    ["/events/xxx",
     "/events/xxx/sign_up",
     "/events/xxx/sandbox",
     "/event_plots/iris_test"]
)
def test_check_unknown_events(client_session, page):
    client, _ = client_session

    # trigger that the event does not exist
    with login_scope(client, 'test_user', 'test') as client:
        rv = client.get(page)
        assert rv.status_code == 302
        assert rv.location == 'http://localhost/problems'
        with client.session_transaction() as cs:
            flash_message = dict(cs['_flashes'])
        assert "no event named" in flash_message['message']


def test_problems(client_session):
    client, _ = client_session

    # GET: access the problems page without login
    rv = client.get('/problems')
    assert rv.status_code == 200
    assert b'Hi User!' not in rv.data
    assert b'number of participants =' in rv.data
    assert b'Iris classification' in rv.data
    assert b'Boston housing price regression' in rv.data

    # GET: access the problems when logged-in
    with login_scope(client, 'test_user', 'test') as client:
        rv = client.get('/problems')
        assert rv.status_code == 200
        assert b'Hi User!' in rv.data
        assert b'number of participants =' in rv.data
        assert b'Iris classification' in rv.data
        assert b'Boston housing price regression' in rv.data


def test_problem(client_session):
    client, session = client_session

    # Access a problem that does not exist
    rv = client.get('/problems/xxx')
    assert rv.status_code == 302
    assert rv.location == 'http://localhost/problems'
    with client.session_transaction() as cs:
        flash_message = dict(cs['_flashes'])
    assert flash_message['message'] == "Problem xxx does not exist"
    rv = client.get('/problems/xxx', follow_redirects=True)
    assert rv.status_code == 200

    # GET: looking at the problem without being logged-in
    rv = client.get('problems/iris')
    assert rv.status_code == 200
    assert b'Iris classification' in rv.data
    assert b'Current events on this problem' in rv.data
    assert b'Keywords' in rv.data

    # GET: looking at the problem being logged-in
    with login_scope(client, 'test_user', 'test') as client:
        rv = client.get('problems/iris')
        assert rv.status_code == 200
        assert b'Iris classification' in rv.data
        assert b'Current events on this problem' in rv.data
        assert b'Keywords' in rv.data


def test_user_event(client_session):
    client, session = client_session

    # behavior when a user is not approved yet
    add_user(session, 'xx', 'xx', 'xx', 'xx', 'xx', access_level='asked')
    with login_scope(client, 'xx', 'xx') as client:
        rv = client.get('/events/iris_test')
        assert rv.status_code == 302
        assert rv.location == 'http://localhost/problems'
        with client.session_transaction() as cs:
            flash_message = dict(cs['_flashes'])
        assert (flash_message['message'] ==
                "Your account has not been approved yet by the administrator")

    # trigger that the event does not exist
    with login_scope(client, 'test_user', 'test') as client:
        rv = client.get('/events/xxx')
        assert rv.status_code == 302
        assert rv.location == 'http://localhost/problems'
        with client.session_transaction() as cs:
            flash_message = dict(cs['_flashes'])
        assert "no event named" in flash_message['message']

    # GET
    with login_scope(client, 'test_user', 'test') as client:
        rv = client.get('events/iris_test')
        assert rv.status_code == 200
        assert b'Iris classification' in rv.data
        assert b'Rules' in rv.data
        assert b'RAMP on iris' in rv.data


def test_sign_up_for_event(client_session):
    client, session = client_session

    # trigger that the event does not exist
    with login_scope(client, 'test_user', 'test') as client:
        rv = client.get('/events/xxx/sign_up')
        assert rv.status_code == 302
        assert rv.location == 'http://localhost/problems'
        with client.session_transaction() as cs:
            flash_message = dict(cs['_flashes'])
        assert "no event named" in flash_message['message']

    # GET: sign-up to a new controlled event
    add_user(session, 'yy', 'yy', 'yy', 'yy', 'yy', access_level='user')
    with login_scope(client, 'yy', 'yy') as client:
        rv = client.get('/events/iris_test/sign_up')
        assert rv.status_code == 302
        assert rv.location == 'http://localhost/problems'
        with client.session_transaction() as cs:
            flash_message = dict(cs['_flashes'])
        assert "Sign-up request is sent" in flash_message['Request sent']
        # make sure that the database has been updated for our session
        session.commit()
        event_team = get_event_team_by_name(session, 'iris_test', 'yy')
        assert not event_team.approved

    # GET: sign-up to a new uncontrolled event
    event = get_event(session, 'boston_housing_test')
    event.is_controled_signup = False
    session.commit()
    with login_scope(client, 'yy', 'yy') as client:
        rv = client.get('/events/boston_housing_test/sign_up')
        assert rv.status_code == 302
        assert (rv.location ==
                'http://localhost/events/boston_housing_test/sandbox')
        with client.session_transaction() as cs:
            flash_message = dict(cs['_flashes'])
        assert "is signed up for" in flash_message['Successful sign-up']
        # make sure that the database has been updated for our session
        session.commit()
        event_team = get_event_team_by_name(session, 'boston_housing_test',
                                            'yy')
        assert event_team.approved


# def test_sandbox(client_session):
#     client, session = client_session


def test_event_plots(client_session):
    client, session = client_session

    # trigger that the event does not exist
    with login_scope(client, 'test_user', 'test') as client:
        rv = client.get('/events_plots/xxx/sign_up')
        assert rv.status_code == 302
        assert rv.location == 'http://localhost/problems'
        with client.session_transaction() as cs:
            flash_message = dict(cs['_flashes'])
        assert "no event named" in flash_message['message']
