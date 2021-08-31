"""
Tests for TACC JobManager Class


Note:


References:

"""
import os
import pdb
import pytest
import posixpath
from dotenv import load_dotenv
from unittest.mock import patch

from taccjm.TACCJobManager import TACCJobManager, TJMCommandError
from taccjm.SSHClient2FA import SSHClient2FA
from paramiko import SSHException, AuthenticationException, BadHostKeyException

__author__ = "Carlos del-Castillo-Negrete"
__copyright__ = "Carlos del-Castillo-Negrete"
__license__ = "MIT"

# Note: .env file in tests directory must contain TACC_USER and TACC_PW variables defined
load_dotenv()

global SYSTEM, USER, PW, SYSTEM, ALLOCATION
USER = os.environ.get("TACCJM_USER")
PW = os.environ.get("TACCJM_PW")
SYSTEM = os.environ.get("TACCJM_SYSTEM")
ALLOCATION = os.environ.get("TACCJM_ALLOCATION")

# JM will be the job manager instance that should be initialized once but used by all tests.
# Note the test_init test initializes the JM to begin with, but if only running one other test,
# the first test to run will initialize the JM for the test session.
global JM
JM = None


def _check_init(mfa):
    global JM
    if JM is None:
        # Initialize taccjm that will be used for tests - use special tests dir
        JM = TACCJobManager(SYSTEM, user=USER, psw=PW, mfa=mfa, working_dir="test-taccjm")


def test_init(mfa):
    """Testing initializing class and class helper functions"""

    global JM
    # Initialize taccjm that will be used for tests - use special tests dir
    JM = TACCJobManager(SYSTEM, user=USER, psw=PW, mfa=mfa, working_dir="test-taccjm")

    # Invalid TACC system specified
    with pytest.raises(ValueError):
        bad = TACCJobManager("foo", user=USER, psw=PW, mfa=mfa)

    # Invalid working directory specified, no tricky business allowed with ..
    with pytest.raises(ValueError):
        bad = TACCJobManager(SYSTEM, user=USER, psw=PW, mfa=mfa, working_dir="../test-taccjm")
    with pytest.raises(ValueError):
        bad = TACCJobManager(SYSTEM, user=USER, psw=PW, mfa=mfa, working_dir="test-taccjm/..")
    with pytest.raises(ValueError):
        bad = TACCJobManager(SYSTEM, user=USER, psw=PW, mfa=mfa, working_dir="test-taccjm/../test")

    # Command that should work, also test printing to stdout the output
    assert JM._execute_command('echo test') == 'test\n'

     # Tests command that fails due to SSH error, which we mock from the paramiko client class.
    with patch.object(SSHClient2FA, 'exec_command', side_effect=SSHException('Mock ssh exception')):
        with pytest.raises(SSHException):
             JM._execute_command('echo test')

    # Test commands that fails because of non-zero return code
    with pytest.raises(TJMCommandError):
        JM._execute_command('foo')

    # Test making directory (remove it first)
    test_dir = posixpath.join(JM.trash_dir, 'test')
    try:
        JM._execute_command(f"rmdir {test_dir}")
    except:
        pass
    JM._mkdir(test_dir)

    # Test making directory that will fail
    with pytest.raises(TJMCommandError):
        JM._mkdir(posixpath.join(JM.trash_dir, 'test/will/fail'))

    # Test Update dictionary keys utility
    d = {'a': 1, 'b':{'a':1, 'b':2}}
    new = JM._update_dic_keys(d, a=2, b={'b':3})
    assert d['a']==2
    assert d['b']['b']==3


def test_files(mfa):
    """Test listing, sending, and getting files and directories"""
    global JM

    _check_init(mfa)

    # List files in path that exists and doesnt exist
    assert 'test-taccjm-apps' in JM.list_files(JM.scratch_dir)
    with pytest.raises(TJMCommandError):
         JM.list_files('/bad/path')

    # Send file - Try sending test application script to apps directory
    test_file = '/'.join([JM.apps_dir, 'test_file'])
    JM.upload('./tests/test_app/assets/run.sh', test_file)
    assert 'test_file' in JM.list_files(JM.apps_dir)

    # Test peaking at a file just sent
    first = '#### BEGIN SCRIPT LOGIC'
    first_line = JM.peak_file(test_file, head=1)
    assert first in first_line
    last = '${command} ${command_opts} >>out.txt 2>&1'
    last_line = JM.peak_file(test_file, tail=1)
    assert last in last_line
    both_lines = JM.peak_file(test_file)

    with pytest.raises(Exception):
         JM.peak_file('/bad/path')

    # Send directory - Now try sending whole assets directory
    test_folder = JM.apps_dir + '/test_folder'
    JM.upload('./tests/test_app/assets', test_folder)
    files = JM.list_files(JM.apps_dir)
    assert 'test_folder' in files
    assert '.hidden_file' not in files

    # Send directory - Now try sending whole assets directory, include hidden files
    test_folder_hidden = '/'.join([JM.apps_dir, 'test_folder_hidden'])
    JM.upload('./tests/test_app/assets', test_folder_hidden)
    assert 'test_folder_hidden' in JM.list_files(path=JM.apps_dir)
    assert '.hidden_file' in JM.list_files(path=test_folder_hidden)

    # Get test file
    JM.download(test_file, './tests/test_file')
    assert os.path.isfile('./tests/test_file')
    os.remove('./tests/test_file')

    # Get test folder
    JM.download(test_folder, './tests/test_folder')
    assert os.path.isdir('./tests/test_folder')
    assert os.path.isfile('./tests/test_folder/run.sh')
    os.system('rm -rf ./tests/test_folder')


def test_templating(mfa):
    """Test loading project configuration files and templating json files"""
    global JM
    _check_init(mfa)

    proj_conf_path = './tests/test_app/project.ini'
    app_config = JM.load_templated_json_file('./tests/test_app/app.json', proj_conf_path)
    assert app_config['name']=='test_app--1.0.0'
    with pytest.raises(FileNotFoundError):
        JM.load_templated_json_file('./tests/test_app/not_found.json', proj_conf_path)

def test_deploy_app(mfa):
    """Test deploy applications """
    global JM
    _check_init(mfa)

    # Test deploying app when sending files to system is failing
    with patch.object(TACCJobManager, 'upload', side_effect=Exception('Mock file send error')):
        with pytest.raises(Exception) as e:
            bad_deploy = JM.deploy_app(local_app_dir='./tests/test_app', overwrite=True)
    # Test deploying app with bad config (missing required config)
    with pytest.raises(Exception) as e:
        bad_deploy = JM.deploy_app(local_app_dir='./tests/test_app', app_config_file='app_2.json',
                overwrite=True)

    # Deploy app (should not exist to begin with)
    test_app = JM.deploy_app(local_app_dir='./tests/test_app', overwrite=True)
    assert test_app['name']=='test_app--1.0.0'

    # Now try without overwrite and this will fail
    with pytest.raises(Exception):
        test_app = JM.deploy_app(local_app_dir='./tests/test_app')


def test_jobs(mfa):
    """Test setting up a job."""
    global JM
    _check_init(mfa)

    # Make sure app is deployed
    test_app = JM.deploy_app(local_app_dir='./tests/test_app', overwrite=True)

    # Now try setting up test job, but don't stage inputs
    test_config = JM.setup_job(local_job_dir='./tests/test_app',
            job_config_file='job.json', stage=False)
    assert test_config['appId']=='test_app--1.0.0'
    # We didn't stage the inputs, so this should hold
    assert test_config['job_id'] not in JM.get_jobs()

    # Now try setting up test job
    job_config = JM.setup_job(local_job_dir='./tests/test_app', job_config_file='job.json')
    assert job_config['appId']=='test_app--1.0.0'

    # Get job we se just set up
    jobs = JM.get_jobs()
    assert job_config['job_id'] in jobs

    # Fail setting up job -> Sending input file fails
    with patch.object(TACCJobManager, 'upload',
            side_effect=Exception('Mock upload file error')):
        with pytest.raises(Exception) as e:
            job_config = JM.setup_job(local_job_dir='./tests/test_app', job_config_file='job.json')

    # Update job config to include email and allocation
    job_config = JM.setup_job(job_config,
            email="test@test.com", allocation=ALLOCATION)
    assert job_config['email']=="test@test.com"
    assert job_config['allocation']==ALLOCATION

    # Get job config now, should be updated
    new_job_config = JM.get_job(job_config['job_id'])
    assert new_job_config['email']=="test@test.com"
    assert new_job_config['allocation']==ALLOCATION

    # Fail to save job config -> Example bad job_dir path
    with pytest.raises(Exception) as e:
        bad_config = job_config
        bad_config['job_dir'] = '/bad/path'
        JM._save_job_config(bad_config)

    # Fail to load job config -> Example: bad job id
    with pytest.raises(Exception) as e:
        bad_job = JM.get_job('bad_job')

    # Get input job file from job with input file
    input_file_path = JM.get_job_data(job_config['job_id'], 'test_input_file',
            dest_dir='./tests')
    with open(input_file_path, 'r') as f:
        assert f.read()=="hello\nworld\n"

    # Get job file that doesn't exist
    with pytest.raises(Exception) as e:
        bad_file = JM.get_job_data(job_config['job_id'], 'bad_file')

    # Fail to get job file (some download error maybe)
    with patch.object(TACCJobManager, 'download',
            side_effect=Exception('Mock download file error')):
        with pytest.raises(Exception) as e:
            bad_file = JM.get_job_data(job_config['job_id'], 'test_input_file', dest_dir='./tests')

    # Cleanup files just downloaded
    os.remove(input_file_path)
    os.rmdir(os.path.join('.', 'tests', job_config['job_id']))

    # Send job file
    sent_file_path = JM.send_job_data(job_config['job_id'],
            './tests/test_send_file', dest_dir='.')
    job_files = JM.ls_job(job_config['job_id'])
    assert 'test_send_file' in job_files

    # Fail to send job file
    #with pytest.raises(Exception) as e:
    bad_send = JM.send_job_data(job_config['job_id'], './tests/bad_file', dest_dir='.')

    # Peak at job we just sent
    input_file_text = JM.peak_job_file(job_config['job_id'], 'test_send_file')
    assert input_file_text=="hello\nagain\n"

    # Fail to submit job because SLURM error
    with patch.object(TACCJobManager, '_execute_command',
            return_value="FAILED\n"):
        with pytest.raises(Exception) as e:
            bad_submit = JM.submit_job(job_config['job_id'])

    # Cancel job before its submitted
    with pytest.raises(Exception) as e:
        bad_cancel = JM.cancel_job(job_config['job_id'])

    # Succesfully submit job
    submitted_job = JM.submit_job(job_config['job_id'])
    assert submitted_job['slurm_id'] is not None

    # Fail to try to submit job again
    with pytest.raises(Exception) as e:
        _ = JM.submit_job(job_config['job_id'])

    # Forced failure to cancel job -> slurm error
    with patch.object(TACCJobManager, '_execute_command',
            side_effect=Exception('Mock slurm error')):
        with pytest.raises(Exception) as e:
            _ = JM.cancel_job(job_config['job_id'])

    # Successfully cancel job we just submitted
    canceled = JM.cancel_job(job_config['job_id'])

    # Fail to re-cancel job
    with pytest.raises(Exception) as e:
        bad_cancel = JM.cancel_job(job_config['job_id'])

    # Fail to submit job because of slurm error
    with patch.object(TACCJobManager, '_execute_command',
            side_effect=Exception('Execute command error')):
        with pytest.raises(Exception) as e:
            bad_deploy = JM.cancel_job(job_config['job_id'])

    # Cleanup non existent job
    bad_cleanup = JM.cleanup_job('bad_job')

    # Cleanup jobs we set-up
    _ = JM.cleanup_job(job_config['job_id'])



# def test_main(capsys):
#     """CLI Tests"""
#     # capsys is a pytest fixture that allows asserts agains stdout/stderr
#     # https://docs.pytest.org/en/stable/capture.html
#     main(["7"])
#     captured = capsys.readouterr()
#     assert "The 7-th Fibonacci number is 13" in captured.out
