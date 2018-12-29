import os
import shutil

import pytest

import numpy as np
from numpy.testing import assert_allclose
import pandas as pd
from pandas.testing import assert_frame_equal

from ramputils import read_config
from ramputils import generate_ramp_config
from ramputils.testing import path_config_example

from rampdb.exceptions import DuplicateSubmissionError
from rampdb.exceptions import MissingSubmissionFileError
from rampdb.exceptions import MissingExtensionError
from rampdb.exceptions import TooEarlySubmissionError
from rampdb.exceptions import UnknownStateError
from rampdb.model import Event
from rampdb.model import Model
from rampdb.model import Submission
from rampdb.testing import add_events
from rampdb.testing import add_problems
from rampdb.testing import add_users
from rampdb.testing import create_toy_db
from rampdb.testing import create_test_db
from rampdb.testing import sign_up_teams_to_events
from rampdb.utils import setup_db
from rampdb.utils import session_scope

from rampdb.tools.submission import add_submission

from rampdb.tools.submission import get_event_nb_folds
from rampdb.tools.submission import get_predictions
from rampdb.tools.submission import get_scores
from rampdb.tools.submission import get_submission_by_id
from rampdb.tools.submission import get_submission_by_name
from rampdb.tools.submission import get_submission_state
from rampdb.tools.submission import get_submission_error_msg
from rampdb.tools.submission import get_submission_max_ram
from rampdb.tools.submission import get_submissions
from rampdb.tools.submission import get_time

from rampdb.tools.submission import set_predictions
from rampdb.tools.submission import set_scores
from rampdb.tools.submission import set_submission_error_msg
from rampdb.tools.submission import set_submission_max_ram
from rampdb.tools.submission import set_submission_state
from rampdb.tools.submission import set_time

from rampdb.tools.submission import score_submission
from rampdb.tools.submission import submit_starting_kits

HERE = os.path.dirname(__file__)


@pytest.fixture(scope='module')
def database_config():
    return read_config(path_config_example(), filter_section='sqlalchemy')


@pytest.fixture(scope='module')
def config():
    return read_config(path_config_example())


@pytest.fixture
def base_db(config):
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


def _change_state_db(session):
    # change the state of one of the submission in the iris event
    submission_id = 1
    sub = (session.query(Submission)
                    .filter(Submission.id == submission_id)
                    .first())
    sub.set_state('trained')
    session.commit()


@pytest.fixture(scope='module')
def session_scope_module(config):
    try:
        create_toy_db(config)
        with session_scope(config['sqlalchemy']) as session:
            _change_state_db(session)
            yield session
    finally:
        shutil.rmtree(config['ramp']['deployment_dir'], ignore_errors=True)
        db, Session = setup_db(config['sqlalchemy'])
        with db.connect() as conn:
            session = Session(bind=conn)
            session.close()
        Model.metadata.drop_all(db)


def _setup_sign_up(session, config):
    # asking to sign up required a user, a problem, and an event.
    add_users(session)
    add_problems(session, config)
    add_events(session)
    sign_up_teams_to_events(session, config)
    return config['ramp']['event_name'], 'test_user'


def test_add_submission_create_new_submission(base_db, config):
    # check that we can make a new submission to the database
    # it will require to have already a team and an event
    session = base_db
    event_name, username = _setup_sign_up(session, config)
    ramp_config = generate_ramp_config(config)

    submission_name = 'random_forest_10_10'
    path_submission = os.path.join(
        os.path.dirname(ramp_config['ramp_sandbox_dir']), submission_name
    )
    add_submission(session, event_name, username, submission_name,
                   path_submission, ramp_config['ramp_submissions_dir'], False)
    all_submissions = get_submissions(session, event_name, None)

    # `sign_up_team` make a submission (sandbox) by user. This submission will
    # be the third submission.
    assert len(all_submissions) == 3
    submission = get_submission_by_name(session, event_name, username,
                                        submission_name)
    assert submission.name == submission_name
    submission_file = submission.files[0]
    assert submission_file.name == 'classifier'
    assert submission_file.extension == 'py'
    assert (os.path.join('submission_000000005',
                         'classifier.py') in submission_file.path)


def test_add_submission_too_early_submission(base_db, config):
    # check that we raise an error when the elapsed time was not large enough
    # between the new submission and the previous submission
    session = base_db
    event_name, username = _setup_sign_up(session, config)
    ramp_config = generate_ramp_config(config)

    # check that we have an awaiting time for the event
    event = (session.query(Event)
                    .filter(Event.name == event_name)
                    .one_or_none())
    assert event.min_duration_between_submissions == 900

    # make 2 submissions which are too close from each other
    for submission_idx, submission_name in enumerate(['random_forest_10_10',
                                                      'too_early_submission']):
        path_submission = os.path.join(
            os.path.dirname(ramp_config['ramp_sandbox_dir']), submission_name
        )
        if submission_idx == 1:
            err_msg = 'You need to wait'
            with pytest.raises(TooEarlySubmissionError, match=err_msg):
                add_submission(session, event_name, username, submission_name,
                               path_submission,
                               ramp_config['ramp_submissions_dir'],
                               False)
        else:
            add_submission(session, event_name, username, submission_name,
                           path_submission, ramp_config['ramp_submissions_dir'],
                           False)


def test_make_submission_resubmission(base_db, config):
    # check that resubmitting the a submission with the same name will raise
    # an error
    session = base_db
    event_name, username = _setup_sign_up(session, config)
    ramp_config = generate_ramp_config(config)

    # submitting the starting_kit which is used as the default submission for
    # the sandbox should raise an error
    err_msg = ('Submission "starting_kit" of team "test_user" at event '
               '"iris_test" exists already')
    with pytest.raises(DuplicateSubmissionError, match=err_msg):
        add_submission(session, event_name, username,
                       os.path.basename(ramp_config['ramp_sandbox_dir']),
                       ramp_config['ramp_sandbox_dir'],
                       ramp_config['ramp_submissions_dir'], False)

    # submitting twice a normal submission should raise an error as well
    submission_name = 'random_forest_10_10'
    path_submission = os.path.join(
        os.path.dirname(ramp_config['ramp_sandbox_dir']), submission_name
    )
    # first submission
    add_submission(session, event_name, username, submission_name,
                   path_submission, ramp_config['ramp_submissions_dir'], False)
    # mock that we scored the submission
    set_submission_state(session, 5, 'scored')
    # second submission
    err_msg = ('Submission "random_forest_10_10" of team "test_user" at event '
               '"iris_test" exists already')
    with pytest.raises(DuplicateSubmissionError, match=err_msg):
        add_submission(session, event_name, username, submission_name,
                       path_submission, ramp_config['ramp_submissions_dir'],
                       False)

    # a resubmission can take place if it is tagged as "new" or failed

    # mock that the submission failed during the training
    set_submission_state(session, 5, 'training_error')
    add_submission(session, event_name, username, submission_name,
                   path_submission, ramp_config['ramp_submissions_dir'], False)
    # mock that the submissions are new submissions
    set_submission_state(session, 5, 'new')
    add_submission(session, event_name, username, submission_name,
                   path_submission, ramp_config['ramp_submissions_dir'],
                    False)


def test_add_submission_wrong_submission_files(base_db, config):
    # check that we raise an error if the file required by the workflow is not
    # present in the submission or that it has the wrong extension
    session = base_db
    event_name, username = _setup_sign_up(session, config)
    ramp_config = generate_ramp_config(config)

    submission_name = 'corrupted_submission'
    path_submission = os.path.join(
        os.path.dirname(ramp_config['ramp_sandbox_dir']), submission_name
    )
    os.makedirs(path_submission)

    # case that there is not files in the submission
    err_msg = 'No file corresponding to the workflow element'
    with pytest.raises(MissingSubmissionFileError, match=err_msg):
        add_submission(session, event_name, username, submission_name,
                       path_submission, ramp_config['ramp_submissions_dir'],
                       False)

    # case that there is not file corresponding to the workflow component
    filename = os.path.join(path_submission, 'unknown_file.xxx')
    open(filename, "w+").close()
    err_msg = 'No file corresponding to the workflow element'
    with pytest.raises(MissingSubmissionFileError, match=err_msg):
        add_submission(session, event_name, username, submission_name,
                       path_submission, ramp_config['ramp_submissions_dir'],
                       False)

    # case that we have the correct filename but not the right extension
    filename = os.path.join(path_submission, 'classifier.xxx')
    open(filename, "w+").close()
    err_msg = 'All extensions "xxx" are unknown for the submission'
    with pytest.raises(MissingExtensionError, match=err_msg):
        add_submission(session, event_name, username, submission_name,
                       path_submission, ramp_config['ramp_submissions_dir'],
                       False)


def test_submit_starting_kits(base_db, config):
    session = base_db
    event_name, username = _setup_sign_up(session, config)
    ramp_config = generate_ramp_config(config)

    submit_starting_kits(session, event_name, username,
                         os.path.join(ramp_config['ramp_kits_dir'],
                                      ramp_config['event'],
                                      config['ramp']['submissions_dir']),
                        ramp_config['ramp_submissions_dir'],
                         config['ramp']['sandbox_dir'])

    submissions = get_submissions(session, event_name, None)
    submissions_id = [sub[0] for sub in submissions]
    assert len(submissions) == 5
    expected_submission_name = {'starting_kit', 'starting_kit_test',
                                'random_forest_10_10', 'error'}
    submission_name = set(get_submission_by_id(session, sub_id).name
                          for sub_id in submissions_id)
    assert submission_name == expected_submission_name


@pytest.mark.parametrize(
    "state, expected_id",
    [('new', [2, 5, 6, 7, 8, 9, 10]),
     ('trained', [1]),
     ('tested', []),
     (None, [1, 2, 5, 6, 7, 8, 9, 10])]
)
def test_get_submissions(session_scope_module, state, expected_id):
    submissions = get_submissions(session_scope_module, 'iris_test',
                                  state=state)
    assert len(submissions) == len(expected_id)
    for submission_id, sub_name, sub_path in submissions:
        assert submission_id in expected_id
        assert 'submission_{0:09d}'.format(submission_id) == sub_name
        path_file = os.path.join('submission_{0:09d}'.format(submission_id),
                                 'classifier.py')
        assert path_file in sub_path[0]


def test_get_submission_unknown_state(session_scope_module):
    with pytest.raises(UnknownStateError, match='Unrecognized state'):
        get_submissions(session_scope_module, 'iris_test', state='whatever')


def test_get_submission_by_id(session_scope_module):
    submission = get_submission_by_id(session_scope_module, 1)
    assert isinstance(submission, Submission)
    assert submission.basename == 'submission_000000001'
    assert os.path.exists(os.path.join(submission.path, 'classifier.py'))
    assert submission.state == 'trained'


def test_get_submission_by_name(session_scope_module):
    submission = get_submission_by_name(session_scope_module, 'iris_test',
                                        'test_user', 'starting_kit')
    assert isinstance(submission, Submission)
    assert submission.basename == 'submission_000000001'
    assert os.path.exists(os.path.join(submission.path, 'classifier.py'))
    assert submission.state == 'trained'


def test_get_event_nb_folds(session_scope_module):
    assert get_event_nb_folds(session_scope_module, 'iris_test') == 2


@pytest.mark.parametrize("submission_id, state", [(1, 'trained'), (2, 'new')])
def test_get_submission_state(session_scope_module, submission_id, state):
    assert get_submission_state(session_scope_module, submission_id) == state


def test_set_submission_state(session_scope_module):
    submission_id = 2
    set_submission_state(session_scope_module, submission_id, 'trained')
    assert get_submission_state(session_scope_module, submission_id) == 'trained'


def test_set_submission_state_unknown_state(session_scope_module):
    with pytest.raises(UnknownStateError, match='Unrecognized state'):
        set_submission_state(session_scope_module, 2, 'unknown')


def test_check_time(session_scope_module):
    # check both set_time and get_time function
    submission_id = 1
    path_results = os.path.join(HERE, 'data', 'iris_predictions')
    set_time(session_scope_module, submission_id, path_results)
    submission_time = get_time(session_scope_module, submission_id)
    expected_df = pd.DataFrame(
        {'fold': [0, 1],
         'train' : [0.032130, 0.002414],
         'valid': [0.000583648681640625, 0.000548362731933594],
         'test': [0.000515460968017578, 0.000481128692626953]}
    ).set_index('fold')
    assert_frame_equal(submission_time, expected_df, check_less_precise=True)


def test_check_scores(session_scope_module):
    # check both set_scores and get_scores
    submission_id = 1
    path_results = os.path.join(HERE, 'data', 'iris_predictions')
    set_scores(session_scope_module, submission_id, path_results)
    scores = get_scores(session_scope_module, submission_id)
    multi_index = pd.MultiIndex.from_product(
        [[0, 1], ['train', 'valid', 'test']], names=['fold', 'step']
    )
    expected_df = pd.DataFrame(
        {'acc': [0.604167, 0.583333, 0.733333, 0.604167, 0.583333, 0.733333],
         'error': [0.395833, 0.416667, 0.266667, 0.395833, 0.416667, 0.266667],
         'nll': [0.732763, 2.194549, 0.693464, 0.746132, 2.030762, 0.693992],
         'f1_70': [0.333333, 0.33333, 0.666667, 0.33333, 0.33333, 0.666667]},
        index=multi_index
    )
    assert_frame_equal(scores, expected_df, check_less_precise=True)


def test_check_predictions(session_scope_module):
    # check both set_predictions and get_predictions
    submission_id = 1
    path_results = os.path.join(HERE, 'data', 'iris_predictions')
    set_predictions(session_scope_module, submission_id, path_results)
    predictions = get_predictions(session_scope_module, submission_id)
    for fold_idx in range(2):
        path_fold = os.path.join(path_results, 'fold_{}'.format(fold_idx))
        expected_y_pred_train = np.load(
            os.path.join(path_fold, 'y_pred_train.npz')
        )['y_pred']
        expected_y_pred_test = np.load(
            os.path.join(path_fold, 'y_pred_test.npz')
        )['y_pred']
        assert_allclose(predictions.loc[fold_idx, 'y_pred_train'],
                        expected_y_pred_train)
        assert_allclose(predictions.loc[fold_idx, 'y_pred_test'],
                        expected_y_pred_test)


def test_check_submission_max_ram(session_scope_module):
    # check both get_submission_max_ram and set_submission_max_ram
    submission_id = 1
    expected_ram = 100.0
    set_submission_max_ram(session_scope_module, submission_id, expected_ram)
    amount_ram = get_submission_max_ram(session_scope_module, submission_id)
    assert amount_ram == pytest.approx(expected_ram)


def test_check_submission_error_msg(session_scope_module):
    # check both get_submission_error_msg and set_submission_error_msg
    submission_id = 1
    expected_err_msg = 'tag submission as failed'
    set_submission_error_msg(session_scope_module, submission_id,
                             expected_err_msg)
    err_msg = get_submission_error_msg(session_scope_module, submission_id)
    assert err_msg == expected_err_msg


@pytest.mark.filterwarnings('ignore:F-score is ill-defined and being set')
def test_score_submission(session_scope_module):
    submission_id = 9
    multi_index = pd.MultiIndex.from_product(
        [[0, 1], ['train', 'valid', 'test']], names=['fold', 'step']
    )
    expected_df = pd.DataFrame(
        {'acc': [0.604167, 0.583333, 0.733333, 0.604167, 0.583333, 0.733333],
         'error': [0.395833, 0.416667, 0.266667, 0.395833, 0.416667, 0.266667],
         'nll': [0.732763, 2.194549, 0.693464, 0.746132, 2.030762, 0.693992],
         'f1_70': [0.333333, 0.33333, 0.666667, 0.33333, 0.33333, 0.666667]},
        index=multi_index
    )
    path_results = os.path.join(HERE, 'data', 'iris_predictions')
    with pytest.raises(ValueError, match='Submission state must be "tested"'):
        score_submission(session_scope_module, submission_id)
    set_submission_state(session_scope_module, submission_id, 'tested')
    set_predictions(session_scope_module, submission_id, path_results)
    score_submission(session_scope_module, submission_id)
    scores = get_scores(session_scope_module, submission_id)
    assert_frame_equal(scores, expected_df, check_less_precise=True)
