import glob
import os
import platform
import re
import sys
import subprocess

platform_ids = {'Linux': 'linux', 'Darwin': 'macos', 'Windows': 'win32', 'MINGW64_NT': 'win32'}
platform_id = platform_ids[platform.system().split('-')[0]]
platform_case_sensitive = platform_id != 'win32'

deps_whitelist = set()
deps_whitelist_lower = set()
with open('dlldeps-whitelist.%s' % platform_id, 'r') as f:
    for line in f:
        line = line.rstrip()
        deps_whitelist.add(line)
        deps_whitelist_lower.add(line.lower())

def is_dep_whitelisted(d):
    if platform_case_sensitive:
        return d in deps_whitelist
    else:
        return d.lower() in deps_whitelist_lower

def get_msys_dir_win32():
    for line in subprocess.check_output(['mount']).split('\n'):
        line = line.split()
        if line[1] == 'on' and line[2] == '/':
            return line[0]

def normalize_dep(dep, lib_search_path, strategy):
    def apply_dep_resolution_strategy(dep, lib_search_path, strategy):
        if len(strategy) == 0:
            yield os.path.normpath(dep)
        else:
            for dep1 in strategy[0](dep, lib_search_path):
                yield from apply_dep_resolution_strategy(dep1, lib_search_path, strategy[1:])

    for dep1 in apply_dep_resolution_strategy(dep, lib_search_path, strategy[::-1]):
        if os.path.exists(dep1):
            return dep1
    raise RuntimeError('dependency %s could not be resolved to any valid file')

def find_in_search_path(dep, lib_search_path):
    # if does not exist, look in lib_search_path:
    yield dep
    for path in lib_search_path:
        yield os.path.join(path, dep)

def strip_one_version_component_linux(dep, lib_search_path):
    # XXX: try stripping away last version component
    yield dep
    while True:
        m = re.match(r'^(.*)\.so(\.\d+)(.*)', dep)
        if m:
            dep = '%s.so%s' % (m.group(1), m.group(3))
            yield dep
        else:
            break

def normalize_dep_linux(dep, lib_search_path):
    return normalize_dep(dep, lib_search_path, [strip_one_version_component_linux, find_in_search_path])

def scandeps_linux(lib0):
    for line in subprocess.check_output(['ldd', lib0]).split('\n'):
        if not line: continue
        m = re.match(r'^\s*((\S+) => )?((\S*) \((0x[0-9a-f]+)\)|not found)$', line)
        if m:
            lib = m.group(2) if m.group(2) else m.group(4)
            if lib == 'linux-vdso.so.1': continue
            yield lib

def truncate_framework_dep_macos(dep, lib_search_path):
    # truncate dep at the first occurrence of *.framework/
    comps = os.path.normpath(dep).split(os.path.sep)
    comps1 = []
    for c in comps:
        comps1.append(c)
        if re.match(r'^.*\.framework$', c):
            break
    if len(comps1) < len(comps):
        yield os.path.sep.join(comps1)
    else:
        yield dep

def replace_special_paths_macos(dep, lib_search_path):
    # replace @rpath and similar:
    yield dep
    for pfx in ('@rpath', '@loader_path'):
        m = re.match('^%s/(.*)$' % pfx, dep)
        if m:
            for path in lib_search_path:
                yield os.path.join(path, m.group(1))

def strip_one_version_component_macos(dep, lib_search_path):
    # XXX: try stripping away last version component
    yield dep
    while True:
        m = re.match(r'^(.*)(\.\d+)\.dylib', dep)
        if m:
            dep = '%s.dylib' % m.group(1)
            yield dep
        else:
            break

def normalize_dep_macos(dep, lib_search_path):
    return normalize_dep(dep, lib_search_path, [truncate_framework_dep_macos, strip_one_version_component_macos, replace_special_paths_macos, find_in_search_path])

def is_framework_macos(dep):
    return os.path.isdir(dep) and re.match(r'^.*\.framework$', dep)

def scandeps_macos(lib0):
    if is_framework_macos(lib0): return
    for line in subprocess.check_output(['otool', '-L', lib0]).decode('utf8').split('\n'):
        m = re.match(r'^\s*(\S*) \(.*\)$', line)
        if m:
            lib = m.group(1)
            yield lib

def normalize_dep_win32(dep, lib_search_path):
    return normalize_dep(dep, lib_search_path, [find_in_search_path])

def find_dumpbin_win32():
    msvc_dir = None
    for d1 in ['c:']:
        for d2 in ['Program Files', 'Program Files (x86)']:
            for d3 in ['Microsoft Visual Studio']:
                for d4 in ['2017','2015']:
                    p = os.path.sep.join([d1,d2,d3,d4,''])
                    if os.path.isdir(p): msvc_dir = p
    if not msvc_dir:
        raise RuntimeError('cannot find MSVC directory')
    l = glob.glob(msvc_dir+'Community/VC/Tools/MSVC/*/bin/HostX64/x64/dumpbin.exe')
    l.sort()
    if os.path.isfile(l[-1]):
        return l[-1]
    raise RuntimeError('cannot find dumpbin.exe in MSVC directory')

def scandeps_win32(lib0):
    p = 0
    has_dld = False
    for line in subprocess.check_output([find_dumpbin_win32(), '/dependents', lib0]).split('\n'):
        line = line.strip()
        if re.match(r'.*\bImage has the following dependencies\b.*', line):
            p = 1
            continue
        if re.match(r'.*\bSummary\b.*', line):
            p = 0
            continue
        if re.match(r'.*\bImage has the following delay load dependencies\b.*', line):
            has_dld = True
        if not line or not p: continue
        m = re.match(r'^\s*(\S+)\s*$', line)
        if m:
            lib = m.group(1)
            if re.match(r'(api|ext)-ms-(win|onecore|onecoreuap|mf)-.*.dll', lib, re.IGNORECASE): continue
            if has_dld:
                raise RuntimeError('%s has delay load dependencies' % lib0)
            yield lib

def getdeps(lib0, search_path, recursive=True, search_in_target_path=True):
    def getdeps_aux(lib0, lib_search_path, scandeps_fn, normalize_fn, recursive=True, result=None):
        for lib in scandeps_fn(lib0):
            libn = normalize_fn(lib, lib_search_path)
            if is_dep_whitelisted(libn): continue
            if libn not in result:
                result.add(libn)
                if recursive:
                    getdeps_aux(libn, lib_search_path, scandeps_fn, normalize_fn, True, result)
            continue

    search_path1 = []
    if search_in_target_path:
        target_path = os.path.abspath(os.path.dirname(lib0))
        search_path1.append(target_path)
    for path in search_path:
        search_path1.append(path)

    if platform_id == 'linux':
        scandeps_fn, normalize_fn = scandeps_linux, normalize_dep_linux
    elif platform_id == 'macos':
        scandeps_fn, normalize_fn = scandeps_macos, normalize_dep_macos
    elif platform_id == 'win32':
        scandeps_fn, normalize_fn = scandeps_win32, normalize_dep_win32

    result = set()
    getdeps_aux(lib0, search_path1, scandeps_fn, normalize_fn, recursive, result)
    return result

def main(args):
    try:
        QT5_DIR = os.environ['QT5_DIR']
    except KeyError:
        print('error: environment variable QT5_DIR is not set')

    recursive = False
    if args[0] == '-r':
        args = args[1:]
        recursive = True

    lib_search_path = []
    if platform_id == 'linux':
        lib_search_path.append('/lib')
        lib_search_path.append('/lib/%s-linux-gnu' % platform.machine())
        lib_search_path.append('/usr/lib')
        lib_search_path.append('/usr/lib/%s-linux-gnu' % platform.machine())
        lib_search_path.append('/usr/local/lib')
        lib_search_path.append(os.path.join(QT5_DIR, 'lib'))
    elif platform_id == 'macos':
        lib_search_path.append('/usr/local/lib')
        lib_search_path.append(os.path.join(QT5_DIR, 'lib'))
    elif platform_id == 'win32':
        WINDIR = os.environ.get('WINDIR', 'c:/windows')
        lib_search_path.append('%s/system32' % WINDIR)
        MSYSDIR = get_msys_dir_win32()
        if MSYSDIR is None: MSYSDIR = 'c:/msys64'
        lib_search_path.append('%s/mingw64/bin' % MSYSDIR)

    deps = getdeps(args[0], lib_search_path, recursive)
    for dep in deps: print(dep)

if __name__ == '__main__':
    main(sys.argv[1:])

