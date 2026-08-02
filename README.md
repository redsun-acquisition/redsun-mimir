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
uv venv --python 3.11

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
mmcore install --test-adapters

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
mmcore install --test-adapters

# run the example container via command line
mimir sim
```
</details>

## Wiring a session from YAML

The shipped containers declare their connections in `wire()`. A session built
only from a configuration file has no `wire()` to override, so it must declare
them in a `wiring:` section: **without one the components build and connect to
nothing.**

Do not add this section to a configuration that already backs a container class
with a `wire()` method. The two are applied one after the other, so every rule
would connect a second time and each slot would run twice per emission.

```yaml
wiring:
  - from: det_ctrl.sig_new_data
    to: img_widget.update_layers
  - from: median_ctrl.median
    to: img_widget.update_layers
  - from: median_ctrl.filtered
    to: img_widget.update_layers
  - from: det_widget.sig_property_changed
    to: det_ctrl.set
  - from: det_ctrl.sig_new_configuration
    to: det_widget.on_new_configuration
  - from: motor_widget.sig_motor_move
    to: motor_ctrl.move
  - from: light_widget.sig_toggle_light_request
    to: light_ctrl.trigger
  - from: light_widget.sig_intensity_request
    to: light_ctrl.set
  - from: acq_widget.sig_launch_plan_request
    to: acq_ctrl.launch_plan
  - from: acq_widget.sig_stop_plan_request
    to: acq_ctrl.stop_plan
  - from: acq_widget.sig_pause_resume_request
    to: acq_ctrl.pause_or_resume_plan
  - from: acq_widget.sig_action_request
    to: acq_ctrl.toggle_action_event
  - from: acq_ctrl.sig_plan_done
    to: acq_widget.on_plan_done
  - from: acq_ctrl.sig_action_done
    to: acq_widget.on_action_done
  - from: acq_ctrl.sig_pre_launch_notify
    to: median_ctrl.clear_medians
  - from: acq_ctrl.sig_pre_launch_notify
    to: storage_ctrl.set_plan
  - from: acq_ctrl.sig_plan_done
    to: storage_ctrl.reset_plan
```

Component names are the keys used under `devices:`, `presenters:` and `views:`;
port names are the signal attributes and the names the slots declare. The last
two rules reach `redsun`'s own `StoragePresenter`, which stopped discovering
those signals by itself in 0.11.0.

There is no rule feeding `motor_widget.update_setpoint`: the motor view
subscribes to the axis readbacks themselves, so its labels track the stage even
when a plan is what moved it.

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
