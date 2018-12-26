import logging
import os
import shutil
import subprocess

from git import Repo

from ramputils import generate_ramp_config

from ..utils import setup_db
from ..utils import session_scope

from ..model import Extension
from ..model import Model
from ..model import SubmissionFileType
from ..model import SubmissionFileTypeExtension

from .event import add_problem
from .user import approve_user
from .user import create_user

logger = logging.getLogger('DATABASE')


def create_test_db(config):
    """Create an empty test database and the setup the files for RAMP.

    Parameters
    ----------
    config : dict
        Configuration file containing all ramp information.
    """
    database_config = config['sqlalchemy']
    # we can automatically setup the database from the config file used for the
    # tests.
    ramp_config = generate_ramp_config(config)
    shutil.rmtree(ramp_config['deployment_dir'], ignore_errors=True)
    os.makedirs(ramp_config['ramp_kits_dir'])
    os.makedirs(ramp_config['ramp_data_dir'])
    os.makedirs(ramp_config['ramp_submissions_dir'])
    db, _ = setup_db(database_config)
    Model.metadata.drop_all(db)
    Model.metadata.create_all(db)
    with session_scope(database_config) as session:
        setup_files_extension_type(session)


def setup_toy_db(session, config):
    """Only setup the database by adding some data.

    Parameters
    ----------
    session : :class:`sqlalchemy.orm.Session`
        The session to directly perform the operation on the database.
    """
    add_users(session)
    add_problems(session, config)
    # add_events()
    # sign_up_teams_to_events()
    # submit_all_starting_kits()


def create_toy_db(config):
    """Create a toy dataset with couple of users, problems, events.

    Parameters
    ----------
    session : :class:`sqlalchemy.orm.Session`
        The session to directly perform the operation on the database.
    """
    create_test_db(config)
    with session_scope(config) as session:
        setup_toy_db(session, config)


def add_extension(session, name):
    """Adding a new extension, e.g., 'py'.

    Parameters
    ----------
    session : :class:`sqlalchemy.orm.Session`
        The session to directly perform the operation on the database.
    name : str
        The name of the extension to add if it does not exist.
    """
    extension = (session.query(Extension)
                        .filter(Extension.name == name)
                        .one_or_none())
    if extension is None:
        extension = Extension(name=name)
        logger.info('Adding {}'.format(extension))
        session.add(extension)
        session.commit()


def add_submission_file_type(session, name, is_editable, max_size):
    """Add a new submission file type, e.g., ('code', True, 10 ** 5).

    Parameters
    ----------
    session : :class:`sqlalchemy.orm.Session`
        The session to directly perform the operation on the database.
    name : str
        The name of file type.
    is_editable: bool
        If the file type is editable.
    max_size : int
        The maximum size of the file.

    Notes
    -----
    Should be preceded by adding extensions.
    """
    submission_file_type = (session.query(SubmissionFileType)
                                    .filter(SubmissionFileType.name == name)
                                    .one_or_none())
    if submission_file_type is None:
        submission_file_type = SubmissionFileType(
            name=name, is_editable=is_editable, max_size=max_size)
        logger.info('Adding {}'.format(submission_file_type))
        session.add(submission_file_type)
        session.commit()


def add_submission_file_type_extension(session, type_name, extension_name):
    """Adding a new submission file type extension, e.g., ('code', 'py').

    Parameters
    ----------
    session : :class:`sqlalchemy.orm.Session`
        The session to directly perform the operation on the database.
    type_name : str
        The file type.
    extension_name : str
        The extension name.

    Notes
    -----
    Should be preceded by adding submission file types and extensions.
    """
    submission_file_type = (session.query(SubmissionFileType)
                                   .filter(SubmissionFileType.name == type_name)
                                   .one())
    extension = (session.query(Extension)
                        .filter(Extension.name == extension_name)
                        .one())
    type_extension = (session.query(SubmissionFileTypeExtension)
                             .filter(SubmissionFileTypeExtension.type ==
                                     submission_file_type,
                                     SubmissionFileTypeExtension.extension ==
                                     extension)
                             .one_or_none())
    if type_extension is None:
        type_extension = SubmissionFileTypeExtension(
            type=submission_file_type,
            extension=extension
        )
        logger.info('Adding {}'.format(type_extension))
        session.add(type_extension)
        session.commit()


def setup_files_extension_type(session):
    """Setup the files' extensions and types.

    This function registers the file extensions and types. This function
    should be called after creating the database.

    Parameters
    ----------
    session : :class:`sqlalchemy.orm.Session`
        The session to directly perform the operation on the database.
    """
    extension_names = ['py', 'R', 'txt', 'csv']
    for name in extension_names:
        add_extension(session, name)

    submission_file_types = [
        ('code', True, 10 ** 5),
        ('text', True, 10 ** 5),
        ('data', False, 10 ** 8)
    ]
    for name, is_editable, max_size in submission_file_types:
        add_submission_file_type(session, name, is_editable, max_size)

    submission_file_type_extensions = [
        ('code', 'py'),
        ('code', 'R'),
        ('text', 'txt'),
        ('data', 'csv')
    ]
    for type_name, extension_name in submission_file_type_extensions:
        add_submission_file_type_extension(session, type_name, extension_name)


def _setup_ramp_kits_ramp_data(config, problem_name):
    """Clone ramp-kits and ramp-data repository and setup it up.

    Parameters
    ----------
    config : dict
        Configuration file containing all ramp information.
    problem_name : str
        The name of the problem.
    """
    ramp_config = generate_ramp_config(config)
    problem_kits_path = os.path.join(ramp_config['ramp_kits_dir'],
                                     problem_name)
    ramp_kits_url = 'https://github.com/ramp-kits/{}.git'.format(problem_name)
    ramp_kits_repo = Repo.clone_from(ramp_kits_url, problem_kits_path)

    problem_data_path = os.path.join(ramp_config['ramp_data_dir'],
                                     problem_name)
    ramp_data_url = 'https://github.com/ramp-data/{}.git'.format(problem_name)
    ramp_data_repo = Repo.clone_from(ramp_data_url, problem_data_path)

    current_directory = os.getcwd()
    os.chdir(problem_data_path)
    subprocess.check_output(["python", "prepare_data.py"])
    os.chdir(problem_kits_path)
    # TODO: I don't think that we need to convert the notebook here. It should
    # not be used the related tests.
    subprocess.check_output(["jupyter", "nbconvert", "--to", "html",
                             "{}_starting_kit.ipynb".format(problem_name)])
    os.chdir(current_directory)


def add_users(session):
    """Add dummy users in the database.

    Parameters
    ----------
    session : :class:`sqlalchemy.orm.Session`
        The session to directly perform the operation on the database.
    """
    create_user(
        session, name='test_user', password='test',
        lastname='Test', firstname='User',
        email='test.user@gmail.com', access_level='asked')
    approve_user(session, 'test_user')
    create_user(
        session, name='test_user_2', password='test',
        lastname='Test_2', firstname='User_2',
        email='test.user.2@gmail.com', access_level='asked')
    approve_user(session, 'test_user_2')
    create_user(
        session, name='test_iris_admin', password='test',
        lastname='Admin', firstname='Iris',
        email='iris.admin@gmail.com', access_level='user')


def add_problems(session, config):
    """Add dummy problems into the database.

    Parameters
    ----------
    session : :class:`sqlalchemy.orm.Session`
        The session to directly perform the operation on the database.
    config : dict
        Configuration dictionary containing the ramp information.
    """
    ramp_config = generate_ramp_config(config)
    problems = ['iris', 'boston_housing']
    for problem_name in problems:
        _setup_ramp_kits_ramp_data(config, problem_name)
        add_problem(session, problem_name,
                    ramp_config['ramp_kits_dir'])