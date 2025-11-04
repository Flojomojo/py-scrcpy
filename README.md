# pyscrcpy
A python [scrcpy](https://github.com/Genymobile/scrcpy) client implementation for simple api usage

# Installation
Currently not available on pip, but since it's a single self-contained file, it's very easy to integrate into your project (don't forget the LICENSE :))

# Usage
See [`threaded_example.py`](https://github.com/Flojomojo/py-scrcpy/blob/main/threaded_example.py) for a threaded example and [`unthreaded_example.py`](https://github.com/Flojomojo/py-scrcpy/blob/main/unthreaded_example.py) for a unthreaded example.
You can get the server from the official repo under [releases](https://github.com/Genymobile/scrcpy/releases/latest) under `scrcpy-server-vX.X.X`

# Requirements
1. *Python:* 3.13 or newer (probably also older is fine)
2. *ADB:* `adb` needs to be installed on the system and preferably in the PATH. Alternatively set `ADBUTILS_ADB_PATH` to the adb path.
3. *scrcpy server:* As this is only a client implementation, the server still does the heavy lifting. (Refer to `USAGE`)

# Dependencies
Dependencies are found in the [`pyproject.toml`](https://github.com/Flojomojo/py-scrcpy/blob/main/pyproject.toml), the main ones are:
- [adbutils](https://github.com/openatx/adbutils) for handling adb related operations
- [av](https://github.com/PyAV-Org/PyAV), [numpy](https://github.com/numpy/numpy), and [cv2](https://github.com/opencv/opencv-python) for handling frame decoding

# Limitations & Scope
- *Modern scrcpy only:* Because scrcpy changed heavily in the past, only modern versions of the server are supported (> scrcpy 2.0.0).
- *Video only:* This is a video only implementation. This means the goal of this project is only to get a video feed, not audio, not control.
- *h264 only:* The currently only supported video codec by this project is "h264", even though more might be supported in the future (this is more than plenty for most projects).

