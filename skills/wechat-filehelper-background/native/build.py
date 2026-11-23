"""Build the reviewed file-only bridge using an existing Microsoft x64 toolchain."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

parser=argparse.ArgumentParser()
parser.add_argument('--msvc',type=Path,required=True,help='VC/Tools/MSVC/<version> directory')
parser.add_argument('--sdk',type=Path,required=True,help='Windows Kits/10 directory')
parser.add_argument('--sdk-version',required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parent
compiler=args.msvc/'bin/Hostx64/x64/cl.exe'
if not compiler.is_file():raise SystemExit('Microsoft x64 cl.exe is required; MinGW is not ABI-compatible')
env=os.environ.copy()
for name in ['CL','_CL_','LINK','_LINK_']:env.pop(name,None)
env['VSCMD_SKIP_SENDTELEMETRY']='1'
env['PATH']=str(compiler.parent)+os.pathsep+env.get('PATH','')
env['INCLUDE']=';'.join(map(str,[args.msvc/'include',*(args.sdk/'Include'/args.sdk_version/x for x in ['ucrt','shared','um'])]))
env['LIB']=';'.join(map(str,[args.msvc/'lib/x64',args.sdk/'Lib'/args.sdk_version/'ucrt/x64',args.sdk/'Lib'/args.sdk_version/'um/x64']))
output=root.parent/'assets/filehelper_42053_bridge.dll'
with tempfile.TemporaryDirectory(prefix='filehelper-build-') as build:
    cmd=[str(compiler),'/nologo','/std:c++17','/O2','/MT','/EHsc','/LD','/utf-8','/W4','/DNDEBUG',
         'filehelper_42053.cpp','/Fe:'+str(output),'/Fo:'+str(Path(build)/'filehelper.obj'),
         # No legacy POSIX aliases or COM GUIDs are used. Unresolved symbols remain fatal.
         '/link','/MACHINE:X64','bcrypt.lib','/NODEFAULTLIB:OLDNAMES','/NODEFAULTLIB:uuid',
         '/IMPLIB:'+str(Path(build)/'filehelper.lib'),'/Brepro']
    done=subprocess.run(cmd,cwd=root,env=env,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    print(done.stdout.decode('utf-8',errors='replace'))
    print(done.stderr.decode('utf-8',errors='replace'))
    if done.returncode:raise SystemExit(done.returncode)
print(json.dumps({'binary':str(output),'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}))
