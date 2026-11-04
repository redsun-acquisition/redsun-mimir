# Changelog

What changed in each release, grouped as in
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/). This project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html), and dates are
written `DD-MM-YYYY`. Each entry links the pull request that made it.

Releases up to 0.5.1 are in [LEGACY_CHANGELOG.md](LEGACY_CHANGELOG.md).

<!-- towncrier release notes start -->

## [0.6.0](https://github.com/redsun-acquisition/redsun-mimir/releases/tag/v0.6.0) - 04-11-2026

### Breaking

- `NapariApplication` serves `create_application` only. A session file names `napari` at `configure_application` for the stylesheet. ([#45](https://github.com/redsun-acquisition/redsun-mimir/pull/45))
- The example sessions' stage controls are `redsun`'s built-in positioner: `motor_ctrl` is a `PositionerPresenter` and `motor_widget` a `PositionerView`. A session file pairs them with `pairs: [[motor_widget, motor_ctrl]]`. ([#46](https://github.com/redsun-acquisition/redsun-mimir/pull/46))
- `UC2LaserDevice.enabled` follows the board's intensity: it reads `True` while the intensity is above 0. Writing `False` remembers the intensity and writes 0; writing `True` writes the remembered intensity back, unless an intensity was set while the laser was off. ([#47](https://github.com/redsun-acquisition/redsun-mimir/pull/47))
- `MockLightDevice` built with `binary=True` has no `intensity` signal. ([#47](https://github.com/redsun-acquisition/redsun-mimir/pull/47))
- The example sessions' light controls are `redsun`'s built-in ones: `light_ctrl` is a `LightPresenter` (`redsun.presenter`) and `light_widget` a `LightView` (`redsun.view.qt.builtins`). A session file pairs them with `pairs: [[light_widget, light_ctrl]]`. ([#47](https://github.com/redsun-acquisition/redsun-mimir/pull/47))
- `DetectorPresenter.setup` takes the `Deferrals` that `redsun`'s `AcquisitionPresenter` shares, or none. ([#48](https://github.com/redsun-acquisition/redsun-mimir/pull/48))
- The example sessions' acquisition controls are `redsun`'s built-in ones: `acq_ctrl` is an `AcquisitionPresenter` (`redsun.presenter`) and `acq_widget` an `AcquisitionView` (`redsun.view.qt.builtins`). A session file pairs them with `pairs: [[acq_widget, acq_ctrl]]` and links `acq_ctrl.sig_plan_started` to `median_ctrl.clear_medians`. ([#48](https://github.com/redsun-acquisition/redsun-mimir/pull/48))
- `STREAM` moves from `redsun_mimir.presenter.acquisition` to `redsun_mimir.presenter.detector`. ([#48](https://github.com/redsun-acquisition/redsun-mimir/pull/48))
- The positioner of the example sessions shows each stage's axes in a box named after the stage's `axis` map: `XY-axis`, `Z-axis` and `stage-axis`, titled `XY / axis` and so on, in place of `XY`, `Z` and `stage`. Positions saved under the old names no longer match a box; move the stage to each one again and save it. An `include` list in a session file uses the new names. ([#59](https://github.com/redsun-acquisition/redsun-mimir/pull/59))

  ```yaml
  # before
  presenters:
    motor_ctrl:
      include: [XY]

  # now
  presenters:
    motor_ctrl:
      include: [XY-axis]
  ```

### Added

- `DetectorPresenter` (`redsun_mimir.presenter`) offers the `live_stream` plan through `plan_map`, and holds in `actions` the `ActionManager` the plan waits on. ([#48](https://github.com/redsun-acquisition/redsun-mimir/pull/48))

### Changed

- The example sessions install `redsun.qt.styles.napari.NapariStyle` at `configure_application`, at `FONT_SIZE`, so the window follows the colour scheme between napari's dark and light themes. ([#45](https://github.com/redsun-acquisition/redsun-mimir/pull/45))
- `ImageView` gives its viewer napari's dark theme, in place of the theme in napari's settings, so its canvas is black. ([#45](https://github.com/redsun-acquisition/redsun-mimir/pull/45))
- `CHANGELOG.md` holds the releases after 0.5.1; the earlier ones are in `LEGACY_CHANGELOG.md`. ([#51](https://github.com/redsun-acquisition/redsun-mimir/pull/51))
- `ReadableFlyer` (`redsun_mimir.protocols`) also requires `trigger`, and an async `get_index`. ([#59](https://github.com/redsun-acquisition/redsun-mimir/pull/59))
- `redsun-mimir` requires `redsun>=0.17.0`, `bluesky>=1.16.0`, `napari>=0.10.0`, `fastcs>=0.14.4` and `ophyd-async>=0.21.3`, and its `uc2` extra requires `oxiserial>=0.4.0`. ([#59](https://github.com/redsun-acquisition/redsun-mimir/pull/59), [#60](https://github.com/redsun-acquisition/redsun-mimir/pull/60))
- The acquisition view of the example sessions shows the values a plan was launched with in its form. ([#60](https://github.com/redsun-acquisition/redsun-mimir/pull/60))

### Removed

- `NapariApplication.configure_application` and `stylesheet` (`redsun_mimir.utils.napari`). ([#45](https://github.com/redsun-acquisition/redsun-mimir/pull/45))
- `MotorPresenter` (`redsun_mimir.presenter`), `MotorView` (`redsun_mimir.view`), `DescribesMotors` (`redsun_mimir.protocols`) and the `motor` entries in `redsun.yaml`; `redsun`'s `PositionerPresenter` and `PositionerView` take their place. ([#46](https://github.com/redsun-acquisition/redsun-mimir/pull/46))
- `UC2LaserDevice.trigger`, `UC2LaserDevice.binary`, `MockLightDevice.trigger` and `MockLightDevice.binary`; writing `enabled` switches a light. ([#47](https://github.com/redsun-acquisition/redsun-mimir/pull/47))
- `LightPresenter` (`redsun_mimir.presenter`), `LightView` (`redsun_mimir.view`), `DescribesLights` and `LightProtocol` (`redsun_mimir.protocols`) and the `light` entries in `redsun.yaml`; `redsun`'s `LightPresenter` and `LightView` take their place. ([#47](https://github.com/redsun-acquisition/redsun-mimir/pull/47))
- `AcquisitionPresenter` (`redsun_mimir.presenter`), `AcquisitionView` (`redsun_mimir.view`), `HoldsDeferrals` and `HasActions` (`redsun_mimir.protocols`) and the `acquisition` entries in `redsun.yaml`; `redsun`'s `AcquisitionPresenter` and `AcquisitionView` take their place. ([#48](https://github.com/redsun-acquisition/redsun-mimir/pull/48))
- `LogsAction` (`redsun_mimir.view`) and the `logs` entry in `redsun.yaml`; `redsun`'s `LogWindowAction`, offered as `log-window`, takes their place. ([#55](https://github.com/redsun-acquisition/redsun-mimir/pull/55))

### Fixed

- `MMCamera.read_configuration` and `MMCamera.describe_configuration` list the settings by name, then the properties, so the detector view shows them in the same order on every run. ([#49](https://github.com/redsun-acquisition/redsun-mimir/pull/49))
- The acquisition presenter of the example sessions no longer names the files of a plan launched as the previous plan ends `unknown`. ([#60](https://github.com/redsun-acquisition/redsun-mimir/pull/60))
- The settings tree of `DetectorView` (`redsun_mimir.view`) edits an integer setting wider than 32 bits. ([#60](https://github.com/redsun-acquisition/redsun-mimir/pull/60))
