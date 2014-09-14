try:
	from http.client import HTTPConnection, OK
except ImportError:
	from httplib import HTTPConnection, OK
import os, sys
import subprocess
import unittest
import time
repo_root = os.path.dirname(os.path.dirname(__file__))


class TestInteraction(unittest.TestCase):
	def setUp(self):
		self.port = 9293 # don't collide with real server
		child_env = os.environ.copy()
		child_env['EDIT_SERVER_EDITOR'] = 'cp tests/edited.txt'
		self.server = subprocess.Popen(
			[sys.executable, '-m', 'edit_server', '--port', '9293'],
			env=child_env,
			cwd=repo_root,
		)
		time.sleep(1)

	def tearDown(self):
		self.server.terminate()

	def run_server(self):
		edit_server = './edit-server'
		os.execl(edit_server, edit_server)

	def test_edit_file(self):
		connection = HTTPConnection('localhost', self.port)
		connection.request('POST', '/', "Original text\n")
		response = connection.getresponse()

		self.assertEqual(response.status, OK)
		result = response.read().decode('utf-8')
		self.assertEqual(result, "Replaced text\n")
