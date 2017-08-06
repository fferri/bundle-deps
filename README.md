# bundle-deps

A multi-platform tool to bundle binary dependencies.

Currently supports:
 - Linux
 - macOS
 - Windows (you need MSYS2/mingw64)

Requirements:
 - Python 3.x
 - Windows: Microsoft Visual Studio 2015/2017 (or change how dumpbin.exe is found)

## Usage:

```text
$ python3 bundle-deps/bundle-deps.py -h
error: environment variable QT5_DIR is not set
usage: bundle-deps.py [-h] [-r] [-n] [-v] [-L path] [-W dep] target

positional arguments:
  target                target to scan for required deps

optional arguments:
  -h, --help            show this help message and exit
  -r, --recursive       crawl dependencies recursively
  -n, --dry-run         just print file which get copied without copying them
  -v, --verbose         print performed operations
  -L path, --lib-path path
                        additional path to search for deps
  -W dep, --whitelist-dep dep
                        the full path to a dependency to whitelist (will not be bundled, even if it is required); if it starts with a @ (e.g. @foo) the lines of the file (e.g. foo) will be added as whitelisted deps.
```

