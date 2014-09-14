# Copyright (C) 2009  David Hilley <davidhi@cc.gatech.edu>,
# Tim Cuthbertson <gfxmonk.net>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.
#

from __future__ import absolute_import, print_function
import subprocess
import tempfile
import time
import os
import sys
import re
import stat
import shlex
import socket
import threading
import logging
from optparse import OptionParser

try:
	# py3
	from urllib.parse import quote_plus
	from http.server import BaseHTTPRequestHandler, HTTPServer
	from socketserver import ThreadingMixIn
except ImportError:
	# py2
	from urllib import quote_plus
	from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
	from SocketServer import ThreadingMixIn

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s [%(threadName)s@%(asctime)s]")

OPEN_CMD = shlex.split(os.environ.get('EDIT_SERVER_EDITOR', 'gvim -f'), comments=False)
os.environ['FROM_EDIT_SERVER'] = 'true'

EDITORS = {}
INCREMENTAL = True
DELAY_IN_MINUTES = 5
SYSTEMD_FIRST_SOCKET_FD = 3
TEMP_DIR = None
FILTERS = None
CAREFUL_FILTERING = True

class HttpError(RuntimeError):
	pass

class Editor(object):
	def __init__(self, contents, filter=None, url=None):
		logging.info("Editor using filter: %r", filter)
		self.filter = filter
		self.prefix = "chrome_"

		if url:
			self.prefix += '%%' + quote_plus(url) + '%%'

		self._spawn(contents)
	
	def _spawn(self, contents):
		if self.filter is not None:
			try:
				contents = self.filter.decode(contents)
			except Exception:
				self.filter = None
				logging.error("Failed to decode contents:", exc_info=True)
			else:
				if CAREFUL_FILTERING:
					derived_contents = self.filter.encode(contents)
					re_decoded_contents = self.filter.decode(derived_contents)
					assert contents == re_decoded_contents, "filter is lossy. decoded:\n%s\n\nre-decoded:\n%s" % (contents, re_decoded_contents)

		f = tempfile.NamedTemporaryFile(delete=False, prefix=self.prefix, suffix='.txt', dir=TEMP_DIR)
		filename = f.name
		f.write(contents)
		f.close()
		# spawn editor...
		cmd = OPEN_CMD + [filename]
		logging.info("Spawning editor: %r" % (cmd,))
		self.process = subprocess.Popen(cmd, close_fds=True)
		self.returncode = None
		self.filename = filename

	@property
	def still_open(self):
		return self.returncode is None
	
	@property
	def success(self):
		return self.still_open or self.returncode == 0
	
	@property
	def finished(self):
		return self.returncode is not None

	@property
	def error(self):
		if self.returncode > 0:
			return 'text editor returned %d' % self.returncode
		elif self.returncode < 0:
			return 'text editor died on signal %d' % -(self.returncode)
	
	@property
	def contents(self):
		with open(self.filename, 'r') as f:
			contents = f.read()
		if self.filter is not None:
			contents = Filters.try_call(
				self.filter.encode,
				'encode contents',
				args=(contents,),
				default=contents)
		return contents

	def wait_for_edit(self):
		def _finish():
			del EDITORS[self.filename]

		if not INCREMENTAL:
			self.returncode = self.process.wait()
			_finish()
			return
		last_mod_time = os.stat(self.filename)[stat.ST_MTIME]
		while (True):
			time.sleep(1)
			self.returncode = self.process.poll()
			if self.finished:
				_finish()
				return
			mod_time = os.stat(self.filename)[stat.ST_MTIME]
			if mod_time != last_mod_time:
				logging.info("new mod time: %s, last: %s" % (mod_time, last_mod_time))
				last_mod_time = mod_time
				return

class Filters(object):
	def __init__(self):
		self.filters = []

	def load(self):
		try:
			import env_importer
		except ImportError:
			logging.warn("env_importer not loaded - filters disabled")
			return []
		logging.debug("Loading filters from spec: %r", os.environ.get('EDIT_SERVER_FILTERS', ''))
		loader = env_importer.EnvImporter('EDIT_SERVER_FILTERS')
		self.filters = self.try_call(loader.load_all, desc='load filters', default=[])
		logging.debug("Loaded filters: %r" % (self.filters))
	
	@classmethod
	def try_call(cls, fn, desc, default=None, args=[], kwargs={}):
		try:
			return fn(*args, **kwargs)
		except Exception:
			logging.error("Failed to %s:", desc, exc_info=True)
			return default

	def get_first(self, headers, contents):
		for filter in self.filters:
			match_result = self.try_call(filter.match, 'check filter match', args=(headers, contents))
			if match_result:
				# return True to use `self`, otherwise uses the match_result
				return filter if match_result is True else match_result
		return None

class Handler(BaseHTTPRequestHandler):
	def do_GET(self):
		if self.path == '/status':
				self.send_response(200)
				self.send_header('Content-Type', 'text/plain; charset=utf-8')
				self.end_headers()
				self.wfile.write('edit-server is running.\n')
				return
		self.send_error(404, "GET Not Found: %s" % self.path)

	def _get_editor(self, contents, headers):
		logging.debug("EDITORS: %r" % (EDITORS,))
		filename = self.headers.get("x-file")
		if filename in ('undefined', 'null'): filename = None # that's not very pythonic, is it chaps?
		editor = None

		if filename is not None:
			logging.debug("reusing editor for file: %s" % (filename,))
			editor = EDITORS.get(filename, None)
			if editor is None:
				logging.warn("Could not find existing editor - creating new one for filename: %s", filename)

		if editor is None:
			filter = FILTERS.get_first(headers, contents)
			editor = Editor(contents, filter=filter, url=headers.get('x-url'))
			EDITORS[editor.filename] = editor
		return editor
	
	def _wait_for_edited_contents(self, editor):
		editor.wait_for_edit()

		if editor.success:
			return editor.contents
		else:
			raise HttpError(404, editor.error)
	
	def _respond(self, contents, editor):
		self.send_response(200)
		self.send_header('x-open', str(editor.still_open).lower())
		if editor.still_open:
			self.send_header('x-file', editor.filename)
		self.end_headers()
		self.wfile.write(contents.encode('utf-8'))

	def _delayed_remove(self, filename):
		def delayed_remove():
			logging.debug("sleeping %s mins" % (DELAY_IN_MINUTES,))
			time.sleep(DELAY_IN_MINUTES * 60)
			logging.debug("removing file: %s" % (filename,))
			try:
				os.unlink(filename)
			except Exception:
				logging.error("Unable to unlink: %s" % (filename, ))
		thread = threading.Thread(target=delayed_remove)
		thread.daemon = True
		thread.start()

	def do_POST(self):
		try:
			logging.info(" --- new request --- ")
			logging.debug("Headers:\n%s", self.headers)
			logging.debug("there are %s active editors" % (len(EDITORS),))
			content_length = self.headers.get('content-length')
			if content_length is None:
				self.send_response(411)
				self.end_headers()
				return
			content_length = int(content_length)
			body = self.rfile.read(content_length)
			editor = self._get_editor(contents=body, headers=self.headers)
			contents = self._wait_for_edited_contents(editor)
			self._respond(contents=contents, editor=editor)
			if editor.finished:
				self._delayed_remove(editor.filename)
		except HttpError as e:
			self.send_error(*e.args)
		except Exception:
			logging.exception("Unhandled exception")
			self.send_error(404, "Not Found: %s" % self.path)
		logging.debug("POST complete")

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
	pass

class SocketInheritingHTTPServer(ThreadedHTTPServer):
	"""A HttpServer subclass that takes over an inherited socket from systemd"""
	def __init__(self, address_info, handler, fd, bind_and_activate=True):
		super(SocketInheritingHTTPServer, self).__init__(
			address_info,
			handler,
			bind_and_activate=False
		)
		self.socket = socket.fromfd(fd, self.address_family, self.socket_type)
		if bind_and_activate:
			# NOTE: systemd provides ready-bound sockets, so we only need to activate:
			self.server_activate()

def main():
	global DELAY_IN_MINUTES, INCREMENTAL, OPEN_CMD, TEMP_DIR, FILTERS
	try:
		parser = OptionParser("usage: %prog [OPTIONS] <edit-cmd>")
		parser.add_option("-p", "--port", default=9292, type="int")
		parser.add_option("-d", "--delay", help="delay (in minutes) before deleting unused files", default=5)
		parser.add_option("--tempdir", default=os.environ.get("EDIT_SERVER_TEMP", None), help="location of temporary files (defaults to /tmp, or $EDIT_SERVER_TEMP if defined)")
		parser.add_option("--no-incremental", help="disable incremental edits (a request will block until editor is finished)", default=True, dest='incremental', action='store_false')
		parser.add_option("--no-filters", help="disable context-specific filters (e.g gmail compose filter)", default=True, dest='use_filters', action='store_false')
		opts, args = parser.parse_args()
		port = opts.port
		DELAY_IN_MINUTES = opts.delay
		INCREMENTAL = opts.incremental
		TEMP_DIR = opts.tempdir
		FILTERS = Filters()
		if opts.use_filters:
			FILTERS.load()

		if args:
			OPEN_CMD = args

		logging.info('edit-server PID is %s' % (os.getpid(),))
		server_args = [('localhost', int(port)), Handler]
		if os.environ.get('LISTEN_PID', None) == str(os.getpid()):
			httpserv = SocketInheritingHTTPServer(*server_args, fd=SYSTEMD_FIRST_SOCKET_FD)
			logging.info('edit-server started on socket fd %s' % (SYSTEMD_FIRST_SOCKET_FD,))
		else:
			httpserv = ThreadedHTTPServer(*server_args)
			logging.info('edit-server started on port %s' % (port,))
		httpserv.table = {}
		httpserv.serve_forever()
	except KeyboardInterrupt:
		httpserv.socket.close()
