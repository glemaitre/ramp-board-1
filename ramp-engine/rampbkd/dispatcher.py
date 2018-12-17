import logging
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
from databoard.db_tools import get_new_submissions

from .local import CondaEnvWorker

logger = logging.getLogger('ramp_dispatcher')


class Dispatcher:
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
        # TODO: make that we can count negatively has in joblib
        self.n_worker = n_worker
        self.worker_policy = worker_policy
        self._poison_pill = False
        self._awaiting_worker_queue = Queue()
        self._processing_worker_queue = LifoQueue(maxsize=self.n_worker)
        self.database_config = {
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
        for sub in submissions:
            # create the configuration for the worker
            worker_config = self.config.copy()
            worker_config.update(self.database_config)
            worker_config['ramp_kit_dir'] = os.path.join(
                worker_config['ramp_kit_dir'], sub.event.problem.name)
            worker_config['ramp_data_dir'] = os.path.join(
                worker_config['ramp_data_dir'], sub.event.problem.name)
            # create the worker
            worker = self.worker(worker_config, os.path.basename(sub.path))
            self._awaiting_worker_queue.put_nowait(worker)
            sub.state = 'send_to_training'
            logger.info('Submission {} added to the queue of submission to be '
                        'processed'.format(os.path.basename(sub.path)))

    def launch_workers(self):
        """Launch the awaiting workers if possible."""
        while (not self._processing_worker_queue.full() and
               not self._awaiting_worker_queue.empty()):
            worker = self._awaiting_worker_queue.get()
            logger.info('Starting worker: {}'.format(worker))
            worker.setup()
            worker.launch_submission()
            self._processing_worker_queue.put_nowait(worker)
            logger.info('Store the worker {} into the processing queue'
                        .format(worker))
        else:
            logger.info('The processing queue is full. Waiting for a worker to'
                        ' finish')

    def collect_result(self):
        """Collect result from processed workers."""
        workers = [self._processing_worker_queue.get()
                   for _ in range(self._processing_worker_queue.qsize())]
        if not workers:
            logger.info('No workers are currently waiting or processed.')
            if self.worker_policy is None:
                return
            elif self.worker_policy == 'sleep':
                time.sleep(5)
            elif self.worker_policy == 'exit':
                self._poison_pill = True
        for worker in workers:
            if worker.status == 'running':
                self._processing_worker_queue.put_nowait(worker)
                logger.info('Worker {} is still running'.format(worker))
                time.sleep(0)
            else:
                logger.info('Collecting results from worker {}'.format(worker))
                worker.collect_results()
                worker.teardown()

    def launch(self):
        logger.info('Starting the RAMP dispatcher')
        while not self._poison_pill:
            logger.info('Fetch the new submission from the database')
            self.fetch_from_db()
            logger.info('Launch awaiting workers')
            self.launch_workers()
            logger.info('Collect results')
            self.collect_result()