import platform
import os
import re
import sys
import subprocess

platform_ids = {'Linux': 'linux', 'Darwin': 'macos', 'MINGW64_NT': 'win32'}
platform_id = platform_ids[platform.system().split('-')[0]]

deps_whitelist = set()
with open('dlldeps-whitelist.%s' % platform_id, 'r') as f:
    for line in f:
        deps_whitelist.add(line.rstrip())

QT5_DIR = os.environ['QT5_DIR']

lib_search_path = []
lib_search_path.append('.')
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
    lib_search_path.append('/mingw64/bin')


def getdeps_linux(lib0, result=None, recursive=True):
    if result is None: result = set()
    libdir = os.path.abspath(os.path.dirname(lib0))
    for line in subprocess.check_output(['ldd', lib0]).split('\n'):
        if not line: continue
        m = re.match(r'^\s*((\S+) => )?((\S*) \((0x[0-9a-f]+)\)|not found)$', line)
        if m:
            lib = m.group(2) if m.group(2) else m.group(4)
            if lib == 'linux-vdso.so.1': continue
            libn = normalize_dep_macos(lib, [libdir] + lib_search_path)
            libn = os.path.normpath(libn)
            if not os.path.exists(libn):
                raise RuntimeError('dependency not found: %s (normalized: %s)' % (lib, libn))
            if libn not in result and libn not in deps_whitelist:
                result.add(libn)
                if recursive:
                    getdeps_linux(libn, result, True)
            continue
    return result

def truncate_framework_dep_macos(dep):
    # truncate dep at the first occurrence of *.framework/
    comps = os.path.normpath(dep).split(os.path.sep)
    comps1 = []
    for c in comps:
        comps1.append(c)
        if re.match(r'^.*\.framework$', c):
            break
    if len(comps1) < len(comps):
        return os.path.sep.join(comps1)

def replace_special_paths_macos(dep, lib_search_path):
    # replace @rpath and similar:
    if os.path.exists(dep): return
    for pfx in ('@rpath', '@loader_path'):
        m = re.match('^%s/(.*)$' % pfx, dep)
        if m:
            for path in lib_search_path:
                p = os.path.join(path, m.group(1))
                if os.path.exists(p):
                    return p

def find_in_search_path(dep, lib_search_path):
    # if does not exist, look in lib_search_path:
    if os.path.exists(dep): return
    for path in lib_search_path:
        p = os.path.join(path, dep)
        if os.path.exists(p):
            return p

def strip_one_version_component_macos(dep):
    # XXX: try stripping away last version component
    if os.path.exists(dep): return
    m = re.match(r'^(.*)(\.\d+)\.dylib', dep)
    if m: return '%s.dylib' % m.group(1)

def normalize_dep_macos(dep, lib_search_path):
    dep1 = truncate_framework_dep_macos(dep)
    if dep1: return normalize_dep_macos(dep1, lib_search_path)

    dep1 = replace_special_paths_macos(dep, lib_search_path)
    if dep1: return normalize_dep_macos(dep1, lib_search_path)

    dep1 = find_in_search_path(dep, lib_search_path)
    if dep1: return normalize_dep_macos(dep1, lib_search_path)

    dep1 = strip_one_version_component_macos(dep)
    if dep1: return normalize_dep_macos(dep1, lib_search_path)

    return dep

def is_framework_macos(dep):
    return os.path.isdir(dep) and re.match(r'^.*\.framework$', dep)

def getdeps_macos(lib0, result=None, recursive=True):
    if is_framework_macos(lib0): return
    if result is None: result = set()
    libdir = os.path.abspath(os.path.dirname(lib0))
    for line in subprocess.check_output(['otool', '-L', lib0]).split('\n'):
        m = re.match(r'^\s*(\S*) \(.*\)$', line)
        if m:
            lib = m.group(1)
            libn = normalize_dep_macos(lib, [libdir] + lib_search_path)
            libn = os.path.normpath(libn)
            if not os.path.exists(libn):
                raise RuntimeError('dependency not found: %s (normalized: %s)' % (lib, libn))
            if libn not in result and libn not in deps_whitelist:
                result.add(libn)
                if recursive:
                    getdeps_macos(libn, result, True)
            continue
    return result

def getdeps(lib0, result=None, recursive=True):
    if platform_id == 'linux':
        return getdeps_linux(lib0, result, recursive)
    elif platform_id == 'macos':
        return getdeps_macos(lib0, result, recursive)
    elif platform_id == 'win32':
        return getdeps_win32(lib0, result, recursive)

deps = getdeps(sys.argv[1])
for dep in deps: print(dep)
