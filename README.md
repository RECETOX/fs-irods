## Badges

(Customize these badges with your own links, and check https://shields.io/ or https://badgen.net/ to see which other badges are available.)

| fair-software.eu recommendations | |
| :-- | :--  |
| (1/5) code repository              | [![github repo badge](https://img.shields.io/badge/github-repo-000.svg?logo=github&labelColor=gray&color=blue)](https://github.com/hechth/fs-irods) |
| (2/5) license                      | [![github license badge](https://img.shields.io/github/license/hechth/fs-irods)](https://github.com/hechth/fs-irods) |
| (3/5) community registry           | [![RSD](https://img.shields.io/badge/rsd-fs_irods-00a3e3.svg)](https://www.research-software.nl/software/fs_irods) [![workflow pypi badge](https://img.shields.io/pypi/v/fs_irods.svg?colorB=blue)](https://pypi.python.org/project/fs_irods/) |
| (4/5) citation                     | [![DOI](https://zenodo.org/badge/DOI/<replace-with-created-DOI>.svg)](https://doi.org/<replace-with-created-DOI>) |
| (5/5) checklist                    | [![workflow cii badge](https://bestpractices.coreinfrastructure.org/projects/<replace-with-created-project-identifier>/badge)](https://bestpractices.coreinfrastructure.org/projects/<replace-with-created-project-identifier>) |
| howfairis                          | [![fair-software badge](https://img.shields.io/badge/fair--software.eu-%E2%97%8F%20%20%E2%97%8F%20%20%E2%97%8F%20%20%E2%97%8F%20%20%E2%97%8B-yellow)](https://fair-software.eu) |
| **Other best practices**           | &nbsp; |
| Static analysis                    | [![workflow scq badge](https://sonarcloud.io/api/project_badges/measure?project=hechth_fs-irods&metric=alert_status)](https://sonarcloud.io/dashboard?id=hechth_fs-irods) |
| Coverage                           | [![workflow scc badge](https://sonarcloud.io/api/project_badges/measure?project=hechth_fs-irods&metric=coverage)](https://sonarcloud.io/dashboard?id=hechth_fs-irods) |
| Documentation                      | [![Documentation Status](https://readthedocs.org/projects/fs-irods/badge/?version=latest)](https://fs-irods.readthedocs.io/en/latest/?badge=latest) |
| **GitHub Actions**                 | &nbsp; |
| Build                              | [![build](https://github.com/hechth/fs-irods/actions/workflows/build.yml/badge.svg)](https://github.com/hechth/fs-irods/actions/workflows/build.yml) |
| Citation data consistency          | [![cffconvert](https://github.com/hechth/fs-irods/actions/workflows/cffconvert.yml/badge.svg)](https://github.com/hechth/fs-irods/actions/workflows/cffconvert.yml) |
| SonarCloud                         | [![sonarcloud](https://github.com/hechth/fs-irods/actions/workflows/sonarcloud.yml/badge.svg)](https://github.com/hechth/fs-irods/actions/workflows/sonarcloud.yml) |
| MarkDown link checker              | [![markdown-link-check](https://github.com/hechth/fs-irods/actions/workflows/markdown-link-check.yml/badge.svg)](https://github.com/hechth/fs-irods/actions/workflows/markdown-link-check.yml) |

## How to use fs_irods

PyFilesystem2 extension for iRODS

This package provides two filesystem implementations:

1. **iRODSFS** - PyFilesystem2 (fs) compatible implementation
2. **IRODSFileSystem** - fsspec compatible implementation

The project setup is documented in [project_setup.md](project_setup.md). Feel free to remove this document (and/or the link to this document) if you don't need it.

## Installation

To install fs_irods from GitHub repository, do:

```console
git clone git@github.com:RECETOX/fs-irods.git
cd fs-irods
python -m pip install .
```

For fsspec support, also install fsspec:

```console
python -m pip install fsspec
```

## Usage

### PyFilesystem2 (iRODSFS)

```python
from irods.session import iRODSSession
from fs_irods import iRODSFS

# Create an iRODS session
session = iRODSSession(
    host='localhost',
    port=1247,
    user='rods',
    password='rods',
    zone='tempZone'
)

# Create the filesystem
fs = iRODSFS(session, root='/tempZone/home/rods')

# Use with PyFilesystem2 API
fs.listdir('/')
fs.readbytes('/some/file.txt')
fs.writebytes('/new/file.txt', b'content')
fs.close()
session.cleanup()
```

### fsspec (IRODSFileSystem)

```python
from irods.session import iRODSSession
from fs_irods import IRODSFileSystem

# Option 1: Reuse an existing session
session = iRODSSession(
    host='localhost',
    port=1247,
    user='rods',
    password='rods',
    zone='tempZone'
)
fs = IRODSFileSystem(session=session, root='/tempZone/home/rods')

# Option 2: Provide connection parameters directly
fs = IRODSFileSystem(
    host='localhost',
    port=1247,
    user='rods',
    password='rods',
    zone='tempZone',
    root='/tempZone/home/rods'
)

# Option 3: Use a connection string
fs = IRODSFileSystem('irods://rods+tempZone@localhost:1247/tempZone/home/rods')

# Use with fsspec API
fs.ls('/tempZone/home/rods')
fs.cat_file('/some/file.txt')
fs.pipe_file('/new/file.txt', b'content')

# Or use as context manager
with IRODSFileSystem(session=session) as fs:
    data = fs.cat_file('/path/to/file.txt')

fs.close()
session.cleanup()
```

### Using with other libraries

The fsspec implementation can be used with any library that supports fsspec:

```python
import pandas as pd
from fs_irods import IRODSFileSystem

fs = IRODSFileSystem(host='localhost', port=1247, user='rods',
                     password='rods', zone='tempZone')

# Read CSV directly from iRODS
df = pd.read_csv('irods:///tempZone/data/file.csv', storage_options={'fs': fs})

# Write parquet to iRODS
df.to_parquet('irods:///tempZone/output/data.parquet', storage_options={'fs': fs})
```

## Documentation

Include a link to your project's full documentation here.

## Contributing

If you want to contribute to the development of fs_irods,
have a look at the [contribution guidelines](CONTRIBUTING.md).

## Credits

This package was created with [Cookiecutter](https://github.com/audreyr/cookiecutter) and the [NLeSC/python-template](https://github.com/NLeSC/python-template).
