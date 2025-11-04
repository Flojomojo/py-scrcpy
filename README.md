# pyscrcpy
A python [scrcpy](https://github.com/Genymobile/scrcpy) client implementation for simple api usage

# Usage
See [`threaded_example.py`](https://github.com/Flojomojo/py-scrcpy/blob/main/threaded_example.py) for a threaded example and [`unthreaded_example.py`](https://github.com/Flojomojo/py-scrcpy/blob/main/unthreaded_example.py) for a unthreaded example.
You can get the server from the official repo under [releases](https://github.com/Genymobile/scrcpy/releases/latest) under `scrcpy-server-vX.X.X`

# Dependencies
Dependencies are found in the [`pyproject.toml`](https://github.com/Flojomojo/py-scrcpy/blob/main/pyproject.toml), the main ones are:
- [adbutils](https://github.com/openatx/adbutils) for handling adb related operations
- [av](https://github.com/PyAV-Org/PyAV), [numpy](https://github.com/numpy/numpy), and [cv2](https://github.com/opencv/opencv-python) for handling frame decoding
