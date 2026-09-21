# redsun-mimir

[![License Apache Software License 2.0](https://img.shields.io/pypi/l/redsun-mimir.svg?color=green)](https://github.com/redsun-acquisition/redsun-mimir/raw/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/redsun-mimir.svg?color=green)](https://pypi.org/project/redsun-mimir)
[![Python Version](https://img.shields.io/pypi/pyversions/redsun-mimir.svg?color=green)](https://python.org)
[![codecov](https://codecov.io/gh/redsun-acquisition/redsun-mimir/branch/main/graph/badge.svg)](https://codecov.io/gh/redsun-acquisition/redsun-mimir)

Bundle of [`redsun`](https://github.com/redsun-acquisition/redsun) components for the openUC2 "Mimir" microscope

## About `mimir`

Mimir is the codename for an in-development portable [interferometric scattering microscope](https://en.wikipedia.org/wiki/Interferometric_scattering_microscopy) (iSCAT), with an hardware controller developed by [openUC2](https://openuc2.com/). The hardware is driven from separate processes: [`pymmcore-plus`](https://pymmcore-plus.github.io/pymmcore-plus/) for the camera and the stages, [`pyserial`](https://github.com/pyserial/pyserial) for the openUC2 board. Each runs as a `redsun` service and is reached over PVAccess, served by [`fastcs`](https://github.com/DiamondLightSource/FastCS).

`redsun-mimir` is a bundle of components developed to target the specific hardware and software requirements for real-time acquisition with said microscope.

> [!NOTE]
> This bundle has been used as a staging ground for development in cohesion with the main framework. Some components may be moved to `redsun` itself to be provided as built-in functionalities. Expect breaking changes as the framework evolves.

> [!WARNING]
> The `youseetoo` module has not been fully tested and there is currently no known way of testing it in a continous integration. The service is exercised against a `loop://` serial port, which answers nothing; the board itself is untested. Ensure you can pre-emptively test the components locally.

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

## Installing the napari application hook

`ImageView` embeds a napari viewer but carries no stylesheet of its own: it is
styled by the application it is built under. `NapariApplication` supplies that
application. It serves two hook points, returning the application napari itself
would build (`create_application`) and putting napari's stylesheet on it
(`configure_application`).

A session built only from a configuration file installs it in a `hooks:`
section. One entry serves both points, so a YAML anchor keeps it a single
provider instance:

```yaml
hooks:
  create_application: &napari
    provider: "redsun_mimir.hooks:NapariApplication"
  configure_application: *napari
```

Without it the viewer still works and its canvas still follows the theme in
napari's settings, but nothing sets a stylesheet on the application, so the
layer list, the layer controls and the rest of the Qt chrome keep their default
look.

The shipped containers declare the hook themselves, so `mimir sim` and
`mimir uc2` need no `hooks:` section.

## Services

Every piece of hardware runs in its own process. A service owns the driver, a
`redsun` session starts and stops it, and the device in the session talks to it
over PVAccess. The bundle ships three:

| service | what it owns | arguments |
| --- | --- | --- |
| `mmcore-camera` | one Micro-Manager camera | `--adapter`, `--device` |
| `mmcore-stage` | one Micro-Manager stage | `--adapter`, `--device`, `--axes` |
| `youseetoo-controller` | the openUC2 board's serial port | `--port`, `--baudrate` |

A session declares them beside its devices, and each device names the service
it belongs to:

```yaml
services:
  transport: pv-access
  camera1_ioc:
    plugin_name: redsun-mimir
    plugin_id: mmcore-camera
    prefix: "MIMIR-CAM1:"
    args: ["--adapter", "DemoCamera", "--device", "DCam"]
```

```python
class MimirSimulator(MimirApp, config=_CONFIG):
    mmcamera = declare_device(MMCamera, service="camera1_ioc")
```

A service reads its prefix from the environment the session launches it with,
and the device connects at that prefix, so the session file names it once.

The directory a capture goes to is a session setting:

```yaml
storage:
  base_dir: "D:/mimir-data"   # optional; the user data directory otherwise
```

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
  - from: det_ctrl.sig_new_configuration
    to: img_widget.on_new_configuration
  - from: img_widget.sig_roi_drawn
    to: det_widget.on_roi_drawn
  - from: det_widget.sig_roi_selection
    to: img_widget.set_roi_selection
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
  - from: acq_widget.sig_base_dir_request
    to: acq_ctrl.set_base_dir
  - from: acq_ctrl.sig_base_dir_changed
    to: acq_widget.on_base_dir_changed
  - from: acq_ctrl.sig_pre_launch_notify
    to: median_ctrl.clear_medians
  - from: acq_ctrl.sig_pre_launch_notify
    to: path_provider.set_plan
  - from: acq_ctrl.sig_plan_done
    to: path_provider.reset_plan
  - from: acq_ctrl.sig_base_dir_changed
    to: path_provider.set_base_dir
```

Component names are the keys used under `devices:`, `presenters:` and `views:`;
port names are the signal attributes and the names the slots declare. The three
rules reaching `path_provider` go to the session's own path provider, which is
what names the directory a capture is written to.

There is no rule feeding `motor_widget.update_setpoint`: the motor view
subscribes to the axis readbacks themselves, so its labels track the stage even
when a plan is what moved it.

## Features

- Live data capture.
- Region of interest chosen on the image: Select ROI in a detector's settings
  shows a box over its layer to drag, Confirm applies it, and Clear brings
  the whole sensor back. A change asked for during a plan lands between
  two of its messages.
- Median computation based on square-scan movement for background noise reduction following the procedure described in this [paper](https://opg.optica.org/oe/fulltext.cfm?uri=oe-32-26-46607). The scan's stack of frames is written beside the next capture as `<detector>_scan`; the median stays in memory.
- Every capture and every scan is a run of its own, nested in the live plan's run, with the run it serves and the scan it follows named on its start document.
- The session's log records in a view of their own, from `redsun`.
- Image visualization leveraging [`napari`](https://github.com/napari/napari).
- Data storage in Zarr v3 format via [`acquire-zarr`](https://github.com/acquire-project/acquire-zarr), written by the camera's own service.
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
