#! /usr/bin/env python
import codecs
import os

from setuptools import find_packages, setup

# get __version__ from _version.py
ver_file = os.path.join('ramputils', '_version.py')
with open(ver_file) as f:
    exec(f.read())

DISTNAME = 'ramp-utils'
DESCRIPTION = "Utilities shared across the RAMP bundle"
with codecs.open('README.md', encoding='utf-8-sig') as f:
    LONG_DESCRIPTION = f.read()
MAINTAINER = 'A. Boucaud, B. Kegl, G. Lemaitre, J. Van den Bossche'
MAINTAINER_EMAIL = 'boucaud.alexandre@gmail.com, guillaume.lemaitre@inria.fr'
URL = 'https://github.com/paris-saclay-cds/ramp-board'
LICENSE = 'BSD (3-clause)'
DOWNLOAD_URL = 'https://github.com/paris-saclay-cds/ramp-board'
VERSION = __version__
CLASSIFIERS = ['Intended Audience :: Science/Research',
               'Intended Audience :: Developers',
               'License :: OSI Approved',
               'Programming Language :: Python',
               'Topic :: Software Development',
               'Topic :: Scientific/Engineering',
               'Operating System :: Microsoft :: Windows',
               'Operating System :: POSIX',
               'Operating System :: Unix',
               'Operating System :: MacOS',
               'Programming Language :: Python :: 2.7',
               'Programming Language :: Python :: 3.6',
               'Programming Language :: Python :: 3.7']
INSTALL_REQUIRES = ['bcrypt', 'click', 'pyyaml', 'six']
EXTRAS_REQUIRE = {
    'tests': ['pytest', 'pytest-cov'],
    'docs': ['sphinx', 'sphinx_rtd_theme', 'numpydoc']
}
PACKAGE_DATA = {
    'ramputils': [os.path.join('tests', 'data', 'config.yml'),
                  os.path.join('template', 'database_config.yml'),
                  os.path.join('template', 'ramp_config.yml')]
}

setup(
    name=DISTNAME,
    maintainer=MAINTAINER,
    maintainer_email=MAINTAINER_EMAIL,
    description=DESCRIPTION,
    license=LICENSE,
    url=URL,
    version=VERSION,
    download_url=DOWNLOAD_URL,
    long_description=LONG_DESCRIPTION,
    zip_safe=False,  # the package can run out of an .egg file
    classifiers=CLASSIFIERS,
    packages=find_packages(),
    package_data=PACKAGE_DATA,
    install_requires=INSTALL_REQUIRES,
    extras_require=EXTRAS_REQUIRE,
    entry_points={
        'console_scripts': ['ramp-utils = ramputils.cli:start']
    }
)
