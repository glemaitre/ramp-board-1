import os
import shutil

import pytest

from ramputils import read_config
from ramputils import generate_ramp_config
from ramputils.utils import import_module_from_source
from ramputils.testing import path_config_example

from rampdb.model import Event
from rampdb.model import Model
from rampdb.model import Problem
from rampdb.model import Workflow

from rampdb.utils import setup_db
from rampdb.utils import session_scope

from rampdb.testing import create_test_db
from rampdb.testing import setup_ramp_kits_ramp_data

from rampdb.tools.event import add_event
from rampdb.tools.event import add_problem
from rampdb.tools.event import add_workflow

from rampdb.tools.event import delete_event
from rampdb.tools.event import delete_problem

from rampdb.tools.event import get_event
from rampdb.tools.event import get_problem
from rampdb.tools.event import get_workflow

HERE = os.path.dirname(__file__)


@pytest.fixture(scope='module')
def database_config():
    return read_config(path_config_example(), filter_section='sqlalchemy')


@pytest.fixture(scope='module')
def config():
    return read_config(path_config_example())


@pytest.fixture
def session_scope_function(config):
    try:
        create_test_db(config)
        with session_scope(config['sqlalchemy']) as session:
            yield session
    finally:
        shutil.rmtree(config['ramp']['deployment_dir'], ignore_errors=True)
        db, Session = setup_db(config['sqlalchemy'])
        with db.connect() as conn:
            session = Session(bind=conn)
            session.close()
        Model.metadata.drop_all(db)


def test_check_problem(session_scope_function, config):
    problem_names = ['iris', 'boston_housing']
    for problem_name in problem_names:
        setup_ramp_kits_ramp_data(config, problem_name)
        ramp_config = generate_ramp_config(config)
        add_problem(session_scope_function, problem_name,
                    ramp_config['ramp_kits_dir'])
    problem = get_problem(session_scope_function, problem_names[0])
    assert problem.name == problem_names[0]
    assert isinstance(problem, Problem)
    problem = get_problem(session_scope_function, None)
    assert len(problem) == 2
    assert isinstance(problem, list)
    delete_problem(session_scope_function, problem_names[0])
    problem = get_problem(session_scope_function, problem_names[0])
    assert problem is None
    problem = get_problem(session_scope_function, None)
    assert len(problem) == 1
    assert isinstance(problem, list)


def test_check_workflow(session_scope_function):
    # load the workflow from the iris kit which is in the test data
    for kit in ['iris', 'boston_housing']:
        kit_path = os.path.join(HERE, 'data', '{}_kit'.format(kit))
        problem_module = import_module_from_source(
            os.path.join(kit_path, 'problem.py'), 'problem')
        add_workflow(session_scope_function, problem_module.workflow)
    workflow = get_workflow(session_scope_function, None)
    assert len(workflow) == 2
    assert isinstance(workflow, list)
    workflow = get_workflow(session_scope_function, 'Classifier')
    assert workflow.name == 'Classifier'
    assert isinstance(workflow, Workflow)


def test_check_event(session_scope_function, config):
    # addition of event require some problem
    problem_names = ['iris', 'boston_housing']
    for problem_name in problem_names:
        setup_ramp_kits_ramp_data(config, problem_name)
        ramp_config = generate_ramp_config(config)
        add_problem(session_scope_function, problem_name,
                    ramp_config['ramp_kits_dir'])

    for problem_name in problem_names:
        event_name = '{}_test'.format(problem_name)
        event_title = 'event title'
        add_event(session_scope_function, problem_name, event_name,
                  event_title, is_public=True, force=False)

    event = get_event(session_scope_function, None)
    assert len(event) == 2
    assert isinstance(event, list)

    event = get_event(session_scope_function, 'iris_test')
    assert event.name == 'iris_test'
    assert event.title == event_title
    assert isinstance(event, Event)

    delete_event(session_scope_function, 'iris_test')
    event = get_event(session_scope_function, None)
    assert len(event) == 1