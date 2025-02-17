import os
import sys
import platform
import shutil
import subprocess as sp
import warnings
import socket
import time
from datetime import datetime
import pandas as pd
from ..pyemu_warnings import PyemuWarning

ext = ''
bin_path = os.path.join("..","bin")
if "linux" in platform.platform().lower():
    bin_path = os.path.join(bin_path,"linux")
elif "darwin" in platform.platform().lower():
    bin_path = os.path.join(bin_path,"mac")
else:
    bin_path = os.path.join(bin_path,"win")
    ext = '.exe'

bin_path = os.path.abspath(bin_path)
os.environ["PATH"] += os.pathsep + bin_path


def _istextfile(filename, blocksize=512):


    """
        Function found from:
        https://eli.thegreenplace.net/2011/10/19/perls-guess-if-file-is-text-or-binary-implemented-in-python
        Returns True if file is most likely a text file
        Returns False if file is most likely a binary file
        Uses heuristics to guess whether the given file is text or binary,
        by reading a single block of bytes from the file.
        If more than 30% of the chars in the block are non-text, or there
        are NUL ('\x00') bytes in the block, assume this is a binary file.
    """

    import sys
    PY3 = sys.version_info[0] == 3

    # A function that takes an integer in the 8-bit range and returns
    # a single-character byte object in py3 / a single-character string
    # in py2.
    #
    int2byte = (lambda x: bytes((x,))) if PY3 else chr

    _text_characters = (
        b''.join(int2byte(i) for i in range(32, 127)) +
        b'\n\r\t\f\b')
    block = open(filename,'rb').read(blocksize)
    if b'\x00' in block:
        # Files with null bytes are binary
        return False
    elif not block:
        # An empty file is considered a valid text file
        return True

    # Use translate's 'deletechars' argument to efficiently remove all
    # occurrences of _text_characters from the block
    nontext = block.translate(None, _text_characters)
    return float(len(nontext)) / len(block) <= 0.30


def remove_readonly(func, path, excinfo):
    """remove readonly dirs, apparently only a windows issue
    add to all rmtree calls: shutil.rmtree(**,onerror=remove_readonly), wk"""
    os.chmod(path, 128) #stat.S_IWRITE==128==normal
    func(path)


def run_sweep(pe,slave_dir,pst_name=None,num_slaves=10,exe_name="pestpp-swp",local=True,
              binary=False,master_dir="master_runsweep",cleanup=True):

    if pst_name is not  None:
        assert os.path.exists(os.path.join(slave_dir,pst_name))
    else:
        # pst_files = [f for f in os.listdir(template_dir) if f.lower().endswith(".pst")]
        # if len(pst_files) > 1:
        #     raise Exception("run_sweep() error: 'pst_name' is None "+
        #                     "but more than one '.pst' file found in 'template_dir'")
        # if len(pst_files) == 0:
        #     raise Exception("run_sweep() error: 'pst_name' is None and"+\
        #                     " no '.pst' files in 'template_dir'")
        # pst_file = pst_files[0]
        pst = pe.pst
        pst.write(os.path.join(slave_dir,"master_runsweep.pst"))
        pst_name = "master_runsweep.pst"


    # todo: add autodetect to pestpp-swp for sweep_in.jcb
    if binary:
        raise NotImplementedError("pestpp-swp doesn't support autodetect for binary yet")
        pe.to_binary(os.path.join(slave_dir,"sweep_in.jcb"))
    if not binary:
        pe.to_csv(os.path.join(slave_dir,"sweep_in.csv"))
    if not local:
        raise NotImplementedError("condor not supported yet")
    else:
        print(os.getenv("PATH"))
        start_slaves(slave_dir,exe_name,pst_name,num_slaves=num_slaves,slave_root=".",
                     master_dir=master_dir)

    out_file = os.path.join(master_dir,"sweep_out.csv")
    assert os.path.exists(out_file)
    df = pd.read_csv(out_file,index_col=0)
    df.columns = df.columns.map(str.lower)
    if cleanup:
        shutil.rmtree(master_dir)

    return df



def run(cmd_str,cwd='.',verbose=False):
    """ an OS agnostic function to execute a command line

    Parameters
    ----------
    cmd_str : str
        the str to execute with os.system()

    cwd : str
        the directory to execute the command in

    verbose : bool
        flag to echo to stdout complete cmd str

    Note
    ----
    uses platform to detect OS and adds .exe suffix or ./ prefix as appropriate

    for Windows, if os.system returns non-zero, raises exception

    Example
    -------
    ``>>>import pyemu``

    ``>>>pyemu.helpers.run("pestpp pest.pst")``

    """
    bwd = os.getcwd()
    os.chdir(cwd)
    try:
        exe_name = cmd_str.split()[0]
        if "window" in platform.platform().lower():
            if not exe_name.lower().endswith("exe"):
                raw = cmd_str.split()
                raw[0] = exe_name + ".exe"
                cmd_str = ' '.join(raw)
        else:
            if exe_name.lower().endswith('exe'):
                raw = cmd_str.split()
                exe_name = exe_name.replace('.exe','')
                raw[0] = exe_name
                cmd_str = '{0} {1} '.format(*raw)
            if os.path.exists(exe_name) and not exe_name.startswith('./'):
                cmd_str = "./" + cmd_str


    except Exception as e:
        os.chdir(bwd)
        raise Exception("run() error preprocessing command line :{0}".format(str(e)))
    if verbose:
        print("run():{0}".format(cmd_str))

    try:
        ret_val = os.system(cmd_str)
    except Exception as e:
        os.chdir(bwd)
        raise Exception("run() raised :{0}".format(str(e)))
    os.chdir(bwd)
    if "window" in platform.platform().lower():
        if ret_val != 0:
            raise Exception("run() returned non-zero")


def start_slaves(slave_dir,exe_rel_path,pst_rel_path,num_slaves=None,slave_root="..",
                 port=4004,rel_path=None,local=True,cleanup=True,master_dir=None,
                 verbose=False,silent_master=False):
    """ start a group of pest(++) slaves on the local machine

    Parameters
    ----------
    slave_dir :  str
        the path to a complete set of input files
    exe_rel_path : str
        the relative path to the pest(++) executable from within the slave_dir
    pst_rel_path : str
        the relative path to the pst file from within the slave_dir
    num_slaves : int
        number of slaves to start. defaults to number of cores
    slave_root : str
        the root to make the new slave directories in
    rel_path: str
        the relative path to where pest(++) should be run from within the
        slave_dir, defaults to the uppermost level of the slave dir
    local: bool
        flag for using "localhost" instead of hostname on slave command line
    cleanup: bool
        flag to remove slave directories once processes exit
    master_dir: str
        name of directory for master instance.  If master_dir
        exists, then it will be removed.  If master_dir is None,
        no master instance will be started
    verbose : bool
        flag to echo useful information to stdout
    silent_master : bool
        flag to pipe master output to devnull.  This is only for
        pestpp Travis testing. Default is False

    Note
    ----
    if all slaves (and optionally master) exit gracefully, then the slave
    dirs will be removed unless cleanup is false

    Example
    -------
    ``>>>import pyemu``

    start 10 slaves using the directory "template" as the base case and
    also start a master instance in a directory "master".

    ``>>>pyemu.helpers.start_slaves("template","pestpp","pest.pst",10,master_dir="master")``

    """

    assert os.path.isdir(slave_dir)
    assert os.path.isdir(slave_root)
    if num_slaves is None:
        num_slaves = mp.cpu_count()
    else:
        num_slaves = int(num_slaves)
    #assert os.path.exists(os.path.join(slave_dir,rel_path,exe_rel_path))
    exe_verf = True

    if rel_path:
        if not os.path.exists(os.path.join(slave_dir,rel_path,exe_rel_path)):
            #print("warning: exe_rel_path not verified...hopefully exe is in the PATH var")
            exe_verf = False
    else:
        if not os.path.exists(os.path.join(slave_dir,exe_rel_path)):
            #print("warning: exe_rel_path not verified...hopefully exe is in the PATH var")
            exe_verf = False
    if rel_path is not None:
        assert os.path.exists(os.path.join(slave_dir,rel_path,pst_rel_path))
    else:
        assert os.path.exists(os.path.join(slave_dir,pst_rel_path))
    if local:
        hostname = "localhost"
    else:
        hostname = socket.gethostname()

    base_dir = os.getcwd()
    port = int(port)

    if os.path.exists(os.path.join(slave_dir,exe_rel_path)):
        if "window" in platform.platform().lower():
            if not exe_rel_path.lower().endswith("exe"):
                exe_rel_path = exe_rel_path + ".exe"
        else:
            if not exe_rel_path.startswith('./'):
                exe_rel_path = "./" + exe_rel_path

    if master_dir is not None:
        if master_dir != '.' and os.path.exists(master_dir):
            try:
                shutil.rmtree(master_dir,onerror=remove_readonly)#, onerror=del_rw)
            except Exception as e:
                raise Exception("unable to remove existing master dir:" + \
                                "{0}\n{1}".format(master_dir,str(e)))
        if master_dir != '.':
            try:
                shutil.copytree(slave_dir,master_dir)
            except Exception as e:
                raise Exception("unable to copy files from base slave dir: " + \
                                "{0} to master dir: {1}\n{2}".\
                                format(slave_dir,master_dir,str(e)))

        args = [exe_rel_path, pst_rel_path, "/h", ":{0}".format(port)]
        if rel_path is not None:
            cwd = os.path.join(master_dir,rel_path)
        else:
            cwd = master_dir
        if verbose:
            print("master:{0} in {1}".format(' '.join(args),cwd))
        stdout=None
        if silent_master:
            stdout = open(os.devnull,'w')
        try:
            os.chdir(cwd)
            master_p = sp.Popen(args,stdout=stdout)#,stdout=sp.PIPE,stderr=sp.PIPE)
            os.chdir(base_dir)
        except Exception as e:
            raise Exception("error starting master instance: {0}".\
                            format(str(e)))
        time.sleep(1.5) # a few cycles to let the master get ready


    tcp_arg = "{0}:{1}".format(hostname,port)
    procs = []
    slave_dirs = []
    for i in range(num_slaves):
        new_slave_dir = os.path.join(slave_root,"slave_{0}".format(i))
        if os.path.exists(new_slave_dir):
            try:
                shutil.rmtree(new_slave_dir,onerror=remove_readonly)#, onerror=del_rw)
            except Exception as e:
                raise Exception("unable to remove existing slave dir:" + \
                                "{0}\n{1}".format(new_slave_dir,str(e)))
        try:
            shutil.copytree(slave_dir,new_slave_dir)
        except Exception as e:
            raise Exception("unable to copy files from slave dir: " + \
                            "{0} to new slave dir: {1}\n{2}".format(slave_dir,new_slave_dir,str(e)))
        try:
            if exe_verf:
                # if rel_path is not None:
                #     exe_path = os.path.join(rel_path,exe_rel_path)
                # else:
                exe_path = exe_rel_path
            else:
                exe_path = exe_rel_path
            args = [exe_path, pst_rel_path, "/h", tcp_arg]
            #print("starting slave in {0} with args: {1}".format(new_slave_dir,args))
            if rel_path is not None:
                cwd = os.path.join(new_slave_dir,rel_path)
            else:
                cwd = new_slave_dir

            os.chdir(cwd)
            if verbose:
                print("slave:{0} in {1}".format(' '.join(args),cwd))
            with open(os.devnull,'w') as f:
                p = sp.Popen(args,stdout=f,stderr=f)
            procs.append(p)
            os.chdir(base_dir)
        except Exception as e:
            raise Exception("error starting slave: {0}".format(str(e)))
        slave_dirs.append(new_slave_dir)

    if master_dir is not None:
        # while True:
        #     line = master_p.stdout.readline()
        #     if line != '':
        #         print(str(line.strip())+'\r',end='')
        #     if master_p.poll() is not None:
        #         print(master_p.stdout.readlines())
        #         break
        if silent_master:
            # this keeps travis from thinking something is wrong...
            while True:
                rv = master_p.poll()
                if master_p.poll() is not None:
                    break
                print(datetime.now(), "still running")
                time.sleep(5)
        else:
            master_p.wait()
            time.sleep(1.5) # a few cycles to let the slaves end gracefully
        # kill any remaining slaves
        for p in procs:
            p.kill()
    # this waits for sweep to finish, but pre/post/model (sub)subprocs may take longer
    for p in procs:
        p.wait()
    if cleanup:
        cleanit=0
        while len(slave_dirs)>0 and cleanit<100000: # arbitrary 100000 limit
            cleanit=cleanit+1
            for d in slave_dirs:
                try:
                    shutil.rmtree(d,onerror=remove_readonly)
                    slave_dirs.pop(slave_dirs.index(d)) #if successfully removed
                except Exception as e:
                    warnings.warn("unable to remove slavr dir{0}:{1}".format(d,str(e)),PyemuWarning)

