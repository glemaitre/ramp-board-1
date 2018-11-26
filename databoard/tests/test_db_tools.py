import shutil

import pytest

from databoard import db
from databoard import deployment_path
from databoard.model import User
from databoard.model import NameClashError
from databoard.testing import create_test_db
from databoard.utils import check_password

from databoard.db_tools import create_user
from databoard.db_tools import approve_user


@pytest.fixture
def setup_db():
    try:
        create_test_db()
        yield
    finally:
        shutil.rmtree(deployment_path, ignore_errors=True)


def test_create_user(setup_db):
    name = 'test_user'
    password = 'test'
    lastname = 'Test'
    firstname = 'User'
    email = 'test.user@gmail.com'
    access_level = 'asked'
    create_user(name=name, password=password, lastname=lastname,
                firstname=firstname, email=email, access_level=access_level)
    users = db.session.query(User).all()
    assert len(users) == 1
    user = users[0]
    assert user.name == name
    assert check_password(password, user.hashed_password)
    assert user.lastname == lastname
    assert user.firstname == firstname
    assert user.email == email
    assert user.access_level == access_level


def test_create_user_error_double(setup_db):
    create_user(name='test_user', password='test', lastname='Test',
                firstname='User', email='test.user@gmail.com',
                access_level='asked')
    # check that an error is raised when the username is already used
    err_msg = 'username is already in use and email is already in use'
    with pytest.raises(NameClashError, match=err_msg):
        create_user(name='test_user', password='test', lastname='Test',
                    firstname='User', email='test.user@gmail.com',
                    access_level='asked')
    # TODO: add a team with the name of a user to trigger an error


def test_approve_user(setup_db):
    create_user(name='test_user', password='test', lastname='Test',
                firstname='User', email='test.user@gmail.com',
                access_level='asked')
    user = db.session.query(User).all()[0]
    assert user.access_level == 'asked'
    approve_user(user.name)
    assert user.access_level == 'user'
