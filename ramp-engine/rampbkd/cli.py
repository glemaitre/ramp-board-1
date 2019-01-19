import logging

import click

from ramputils import read_config

from rampbkd.dispatcher import Dispatcher
from rampbkd.dispatcher import CondaEnvWorker


@click.group()
def main():
    """Command-line to launch engine to process RAMP submission."""
    pass


@main.command()
@click.option("--config", default='config.yml',
              help='Configuration file in YAML format')
@click.option('--worker', default='CondaEnvWorker',
              help='Type of worker to use')
@click.option('--n-worker', default=-1,
              help='Number of worker to start in parallel')
@click.option('--hunger-policy', default='exit',
              help='Policy to apply in case that there is no anymore workers'
              'to be processed')
@click.option('-v', '--verbose', is_flag=True)
def dispatcher(config, worker, n_worker, hunger_policy, verbose):
    """Launch the RAMP dispatcher.

    The RAMP dispatcher is in charge of starting RAMP workers, collecting
    results from them, and update the database.
    """
    if verbose:
        logging.basicConfig(format='%(levelname)s %(name)s %(message)s',
                            level=logging.DEBUG)
    config = read_config(config)
    disp = Dispatcher(config=config, worker=globals()[worker],
                      n_worker=n_worker, hunger_policy=hunger_policy)
    disp.launch()


def start():
    main()


if __name__ == '__main__':
    start()
