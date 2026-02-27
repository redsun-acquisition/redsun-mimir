# redsun-mimir

[![License Apache Software License 2.0](https://img.shields.io/pypi/l/redsun-mimir.svg?color=green)](https://github.com/redsun-acquisition/redsun-mimir/raw/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/redsun-mimir.svg?color=green)](https://pypi.org/project/redsun-mimir)
[![Python Version](https://img.shields.io/pypi/pyversions/redsun-mimir.svg?color=green)](https://python.org)
[![codecov](https://codecov.io/gh/redsun-acquisition/redsun-mimir/branch/main/graph/badge.svg)](https://codecov.io/gh/redsun-acquisition/redsun-mimir)

Bundle of [`redsun`](https://github.com/redsun-acquisition/redsun) components for the openUC2 "Mimir" microscope

## About `mimir`

Mimir is the codename for an in-development portable [interferometric scattering microscope](https://en.wikipedia.org/wiki/Interferometric_scattering_microscopy) (iSCAT), with an hardware controller developed by [openUC2](https://openuc2.com/). It employs [`pymmcore-plus`](https://pymmcore-plus.github.io/pymmcore-plus/) for camera control and [`pyserial`](https://github.com/pyserial/pyserial) for motor and laser control.

`redsun-mimir` is a bundle of components developed to target the specific hardware and software requirements for real-time acquisition with said microscope.

> [!NOTE]
> This bundle has been used as a staging ground for development in cohesion with the main framework. Some components may be moved to `redsun` itself to be provided as built-in functionalities. Expect breaking changes as the framework evolves.

> [!WARNING]
> The `youseetoo` module has not been fully tested and there is currently no known way of testing it in a continous integration. Ensure you can pre-emptively test the components locally.

## Installation

It is **strongly reccomended** to install `redsun-mimir` in a virtual environment.

<details open>
<summary>uv (reccomended)</summary>

> Be sure to [install `uv`](https://docs.astral.sh/uv/getting-started/installation/) first.

```bash
# create the venv
uv venv --python 3.10

# activate the environment in...
# ... linux
source .venv/bin/activate

# ... windows
.venv\Scripts\activate

uv pip install redsun-mimir
```

</details>

<details>
<summary>pip</summary>

> You should have Python installed in your machine.

```bash
# create the venv
python -m venv .venv

# activate the environment in...
# ... linux
source .venv/bin/activate

# ... windows
.venv\Scripts\activate

pip install redsun-mimir
```
</details>

### Installing from source

`redsun-mimir` is developed via `uv`; you can clone the repository and install development dependencies:

```bash
git clone https://github.com/redsun-acquisition/redsun-mimir

cd redsun-mimir

uv sync
```

## Running a simulator container

`redsun-mimir` comes with a simple simulation environment with simulated devices for demonstration purposes.

To run it, you have to:

1. install the package in your virtual environment by adding the `sim` optional dependencies;
2. run `mmcore install` (or alternatively one of the methods described [here](https://pymmcore-plus.github.io/pymmcore-plus/install/#installing-micro-manager-device-adapters)).
3. run the container via `mimir sim`.

<details open>
<summary>uv (reccomended)</summary>

```bash
# in your virtual environment
uv pip install redsun-mimir[sim]

# install micro-manager device adapters
mmcore install

# run the example container via command line
mimir sim
```

</details>

<details>
<summary>pip</summary>

```bash
# in your virtual environment
pip install redsun-mimir[sim]

# install micro-manager device adapters
mmcore install

# run the example container via command line
mimir sim
```
</details>

## Features

- Live data capture.
- Median computation based on square-scan movement for background noise reduction following the procedure described in this [paper](https://opg.optica.org/oe/fulltext.cfm?uri=oe-32-26-46607).
- Image visualization leveraging [`napari`](https://github.com/napari/napari).
- Data storage in Zarr v3 format via [`acquire-zarr`](https://github.com/acquire-project/acquire-zarr).
- Manual control of light source and motor drivers.
- Fully extensible via additional components following the `redsun` framework.

## Contributing

Contributions are very welcome. Tests can be run with [pytest], please ensure
the coverage at least stays the same before you submit a pull request.

## License

Distributed under the terms of the [Apache Software License 2.0] license,
`redsun-mimir` is free and open source software

## Issues

If you encounter any problems, please [file an issue] along with a detailed description.

[Apache Software License 2.0]: http://www.apache.org/licenses/LICENSE-2.0
[file an issue]: https://github.com/redsun-acquisition/redsun-mimir/issues
[Redsun]: https://github.com/redsun-acquisition/redsun
[pytest]: https://docs.pytest.org/en/stable/
[pip]: https://pypi.org/project/pip/
[PyPI]: https://pypi.org/
