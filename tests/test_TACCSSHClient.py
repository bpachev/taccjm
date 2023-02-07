"""
Tests for TACC JobManager Class


"""
import pdb
import pytest
from conftest import good_transport, bad_transport, good_channel, bad_channel
from unittest.mock import patch

from paramiko import SSHException
from taccjm.TACCSSHClient import TACCSSHClient
from taccjm.utils import get_ts
from taccjm.exceptions import SSHCommandError

__author__ = "Carlos del-Castillo-Negrete"
__copyright__ = "Carlos del-Castillo-Negrete"
__license__ = "MIT"


class TestTACCSSHClient:
    """
    Unit tests for TACCSSHClient that mock connections.
    """
    @patch.object(TACCSSHClient, 'connect')
    @patch.object(TACCSSHClient, 'execute_command')
    def test_init(self, mock_execute, mock_connect):
        """Testing initializing class and class helper functions"""

        # Tests command that fails due to SSH error, which we mock
        TACCSSHClient('stampede2', user='test', psw='test', mfa=123456)

        # Invalid TACC system specified
        with pytest.raises(ValueError):
            TACCSSHClient("foo", user='test', psw='test', mfa=123456)

        # Invalid working directory specified, no tricky business allowed with ..
        with pytest.raises(ValueError):
            TACCSSHClient('stampede2', user='test', psw='test', mfa=123456,
                          working_dir="../test-taccjm")
        with pytest.raises(ValueError):
            TACCSSHClient('stampede2', user='test', psw='test', mfa=123456,
                          working_dir="test-taccjm/..")
        with pytest.raises(ValueError):
            TACCSSHClient('stampede2', user='test', psw='test', mfa=123456,
                          working_dir="test-taccjm/../test")

    @patch.object(TACCSSHClient, 'process_command')
    @patch.object(TACCSSHClient, 'get_transport')
    def test_execute_command(self, get_transport, process_command):
        """Test executing a command"""

        with patch.object(TACCSSHClient, 'execute_command'):
            with patch.object(TACCSSHClient, 'connect'):
              client = TACCSSHClient('stampede2', user='test', psw='test', mfa=123456)

        # Command that fails to SSH connection, mock through a bad transport object
        get_transport.return_value = bad_transport()
        with pytest.raises(SSHException):
            client.execute_command("pwd")

        # Command succeeds, just mock the exec_command function in
        get_transport.return_value = good_transport()
        res = client.execute_command("pwd", wait=False)
        assert isinstance(res, dict)

        keys = ['id', 'cmd', 'ts', 'status', 'stdout', 'stderr', 'history', 'channel']
        assert all([x in keys for x in res.keys()])

        process_command.return_value = {
            "id": 2,
            "cmd": "pwd",
            "ts": '',
            "status": "STARTED",
            "stdout": "",
            "stderr": "",
            "history": [],
            "channel": good_channel(),
        }
        res = client.execute_command("pwd", wait=True)

    def test_process_command(self):
        """Test processing commands"""

        with patch.object(TACCSSHClient, 'execute_command'):
            with patch.object(TACCSSHClient, 'connect'):
              client = TACCSSHClient('stampede2', user='test', psw='test', mfa=123456)

        # invalid command id
        with pytest.raises(ValueError):
            client.process_command(1)

        # Completed and Failed commands should just be returned as is
        command = {
            "id": len(client.commands),
            "cmd": "pwd",
            "ts": get_ts(),
            "status": "COMPLETE",
            "stdout": "",
            "stderr": "",
            "history": []
        }
        client.commands = [command]
        res = client.process_command(1)
        assert res == command

        # Running command - no wait
        command = {
            "id": len(client.commands),
            "cmd": "pwd",
            "ts": get_ts(),
            "status": "RUNNING",
            "stdout": "",
            "stderr": "",
            "history": [],
            "channel": good_channel(active=True)
        }
        client.commands.append(command)
        # Receive no bytes
        res = client.process_command(2, wait=False)
        assert res['stdout'] == ''
        # Receive only first byte
        res = client.process_command(2, nbytes=1, wait=False)
        assert res['stdout'] == 't'

        # Running command - wait, receive all (nbytes setting shouldn't matter)
        command = {
            "id": len(client.commands),
            "cmd": "pwd",
            "ts": get_ts(),
            "status": "RUNNING",
            "stdout": "",
            "stderr": "",
            "history": [],
            "channel": good_channel(active=True)
        }
        client.commands.append(command)
        res = client.process_command(3, nbytes=1, wait=True)
        assert res['stdout'] == 'test'
        assert res['status'] == 'COMPLETE'

        # Failed command, active, but we 'wait'' for it to finish
        command = {
            "id": len(client.commands),
            "cmd": "pwd",
            "ts": get_ts(),
            "status": "RUNNING",
            "stdout": "",
            "stderr": "",
            "history": [],
            "channel": bad_channel(active=True)
        }
        client.commands.append(command)
        res = client.process_command(4, nbytes=1, wait=True, error=False)
        assert res['stderr'] == 'error'
        assert res['status'] == 'FAILED'

        # Failed command, active, but we 'wait'' for it to finish
        command = {
            "id": len(client.commands),
            "cmd": "pwd",
            "ts": get_ts(),
            "status": "RUNNING",
            "stdout": "",
            "stderr": "",
            "history": [],
            "channel": bad_channel(active=True)
        }
        client.commands.append(command)
        with pytest.raises(SSHCommandError):
            client.process_command(5, wait=True, error=True)


    def test_upload_file(test_file):
        """Test uploadng a file and folder"""

        with patch.object(TACCSSHClient, 'execute_command'):
            with patch.object(TACCSSHClient, 'connect'):
              client = TACCSSHClient('stampede2', user='test', psw='test', mfa=123456)

        test_fname, test_file, test_folder = _setup_local_test_files()

        # Send file - Try sending file only to trash directory
        dest_name = 'test_file'
        dest_path = '/'.join([JM.trash_dir, dest_name])
        JM.upload(test_file, dest_path)
        files = JM.list_files(JM.trash_dir)
        assert dest_name in [f['filename'] for f in files]

        # Send directory - Try sending directory now
        dest_name = 'test_dir'
        dest_dir = '/'.join([JM.trash_dir, dest_name])
        JM.upload(test_folder, dest_dir)
        files = JM.list_files(JM.trash_dir)
        assert dest_name in [f['filename'] for f in files]
        files = JM.list_files(dest_dir)
        assert test_fname in [f['filename'] for f in files]

        # Try sending a file that doesn't exist
        with pytest.raises(FileNotFoundError):
            JM.upload('./does-not-exist', dest_path)

        # Now mock permission and untar-ing error, and unexpcted error
        with patch.object(SSHClient2FA, 'open_sftp',
                side_effect=PermissionError('Mock file permission')):
            with pytest.raises(PermissionError):
                JM.upload(test_folder, dest_dir)
        with patch.object(SSHClient2FA, 'open_sftp',
                side_effect=Exception('Mock other error')):
            with pytest.raises(Exception):
                JM.upload(test_file, dest_path)
        with patch.object(TACCJobManager, '_execute_command',
                side_effect=TJMCommandError(SYSTEM, USER, 'tar...', 1,
                                'mock tar error', '', 'mock tar error')):
            with pytest.raises(TJMCommandError) as t:
                JM.upload(test_folder, dest_dir)

        # Remove test folder and file we sent and local test folder
        JM.empty_trash()
        _cleanup_local_test_files()
