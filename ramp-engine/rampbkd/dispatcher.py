
import logging
import multiprocessing
import os
import sys
import time

PYTHON_MAJOR_VERSION = sys.version_info[0]
if PYTHON_MAJOR_VERSION >= 3:
    from queue import Queue
    from queue import LifoQueue
else:
    from Queue import Queue
    from Queue import LifoQueue

from databoard import ramp_config
from databoard.db_tools import get_submissions
from databoard.db_tools import get_new_submissions
from databoard.db_tools import get_submission_on_cv_folds
from databoard.db_tools import update_all_user_leaderboards
from databoard.db_tools import update_leaderboards
from databoard.db_tools import update_submission_on_cv_fold

from .local import CondaEnvWorker

logger = logging.getLogger('DISPATCHER')


class Dispatcher(object):
    """Dispatcher which schedule workers and communicate with the database.

    The dispatcher uses two queues: a queue containing containing the workers
    which should be launched and a queue containing the workers which are being
    processed. The latter queue has a limited size defined by ``n_workers``.
    Note that these workers can run simultaneously.

    Parameters
    ----------
    config : dict,
        A dictionary with all necessary configuration.
    worker : Worker, default=CondaEnvWorker
        The type of worker to launch. By default, we launch local worker which
        uses ``conda``.
    n_workers : int, default=1
        Maximum number of workers which can run submissions simultaneously.
    worker_policy : {None, 'sleep', 'exit'}
        Policy to apply in case that there is no current workers processed.
    """
    def __init__(self, config, worker=None, n_worker=1, worker_policy=None):
        self.config = config
        self.worker = CondaEnvWorker if worker is None else worker
        self.n_worker = (max(multiprocessing.cpu_count() + 1 + n_worker, 1)
                         if n_worker < 0 else n_worker)
        self.worker_policy = worker_policy
        self._poison_pill = False
        self._awaiting_worker_queue = Queue()
        self._processing_worker_queue = LifoQueue(maxsize=self.n_worker)
        self._processed_submission_queue = Queue()
        self._database_config = {
            'ramp_kit_dir': ramp_config['ramp_kits_path'],
            'ramp_data_dir': ramp_config['ramp_data_path'],
            'ramp_submission_dir': ramp_config['ramp_submissions_path']
        }

    def fetch_from_db(self):
        """Fetch the submission from the database and create the workers."""
        submissions = get_new_submissions(event_name=self.config['event_name'])
        if not submissions:
            logger.info('No new submissions fetch from the database')
            return
        for submission in submissions:
            # create the configuration for the worker
            worker_config = self.config.copy()
            worker_config.update(self._database_config)
            worker_config['ramp_kit_dir'] = os.path.join(
                worker_config['ramp_kit_dir'], submission.event.problem.name)
            worker_config['ramp_data_dir'] = os.path.join(
                worker_config['ramp_data_dir'], submission.event.problem.name)
            # create the worker
            worker = self.worker(worker_config, submission.basename)
            submission.state = 'send_to_training'
            self._awaiting_worker_queue.put_nowait((worker, submission))
            logger.info('Submission {} added to the queue of submission to be '
                        'processed'.format(submission.basename))

    def launch_workers(self):
        """Launch the awaiting workers if possible."""
        while (not self._processing_worker_queue.full() and
               not self._awaiting_worker_queue.empty()):
            worker, submission = self._awaiting_worker_queue.get()
            logger.info('Starting worker: {}'.format(worker))
            worker.setup()
            worker.launch_submission()
            submission.state = 'training'
            self._processing_worker_queue.put_nowait((worker, submission))
            logger.info('Store the worker {} into the processing queue'
                        .format(worker))
        if self._processing_worker_queue.full():
            logger.info('The processing queue is full. Waiting for a worker to'
                        ' finish')

    def collect_result(self):
        """Collect result from processed workers."""
        try:
            workers, submissions = zip(
                *[self._processing_worker_queue.get()
                  for _ in range(self._processing_worker_queue.qsize())]
            )
        except ValueError:
            logger.info('No workers are currently waiting or processed.')
            if self.worker_policy == 'sleep':
                time.sleep(5)
            elif self.worker_policy == 'exit':
                self._poison_pill = True
            return
        for worker, submission in zip(workers, submissions):
            if worker.status == 'running':
                self._processing_worker_queue.put_nowait((worker, submission))
                logger.info('Worker {} is still running'.format(worker))
                time.sleep(0)
            else:
                logger.info('Collecting results from worker {}'.format(worker))
                returncode = worker.collect_results()
                submission.state = ('trained' if not returncode
                                    else 'trained_error')
                self._processed_submission_queue.put_nowait(submission)
                worker.teardown()

    def update_database_results(self):
        """Update the database with the results of ramp_test_submission."""
        while not self._processed_submission_queue.empty():
            submission = self._processed_submission_queue.get_nowait()
            if 'error' in submission.state:
                # do not make any update in case of failed submission
                logger.info('Skip update for {} due to failure during the '
                            'processing'.format(submission.basename))
                continue
            logger.info('Update the results obtained on each fold for '
                        '{}'.format(submission.basename))
            submission_cv_folds = get_submission_on_cv_folds(submission.id)
            for fold_idx, sub_cv_fold in enumerate(submission_cv_folds):
                path_results = os.path.join(
                    self.config['local_predictions_folder'],
                    submission.basename, 'fold_{}'.format(fold_idx)
                )
                update_submission_on_cv_fold(sub_cv_fold, path_results)
                # TODO: test those two last functions
                update_leaderboards(submission.event.name)
                update_all_user_leaderboards(submission.event.name)

    def launch(self):
        """Launch the dispatcher."""
        logger.info('Starting the RAMP dispatcher')
        try:
            while not self._poison_pill:
                self.fetch_from_db()
                self.launch_workers()
                self.collect_result()
                self.update_database_results()
        finally:
            # reset the submissions to 'new' in case of error or unfinished
            # training
            submissions = get_submissions(event_name=self.config['event_name'])
            for submission in submissions:
                if 'training' in submission.state:
                    submission.state = 'new'
        logger.info('Dispatcher killed by the poison pill')
