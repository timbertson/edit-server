from urlparse import urlparse
import logging
import html2text
import re
import cgi

class GmailFilter(object):
	logger = logging.getLogger(__name__ + '.GmailFilter')
	def match(self, headers, contents):
		url = headers.getheader('x-url', None)
		if url is None: return
		url = urlparse(url)
		self.logger.debug("text is from URL: %s" % (url,))
		if url.netloc == 'mail.google.com' and ('<br>' in contents or '<div>' in contents):
			return GmailCodec()

class GmailCodec(object):
	'''
	Converts a (tiny) subset of HTML -> text and back.
	Empirically this should be enough to edit "plain text" in gmail's new compose window,
	but it's somewhat fragile.

	>>> c = GmailCodec()
	>>> content = ("3<div><br></div><div><br></div><div><br></div><div>"
	...            "2</div><div><br></div><div><br></div><div>"
	...            "1</div><div><br></div><div>"
	...            "0</div><div>"
	...            "EOF</div>")

	>>> plaintext = c.decode(content)
	>>> print plaintext
	3
	<BLANKLINE>
	<BLANKLINE>
	<BLANKLINE>
	2
	<BLANKLINE>
	<BLANKLINE>
	1
	<BLANKLINE>
	0
	EOF
	>>> html = c.encode(plaintext)
	>>> print html
	3<br><br><br><br>2<br><br><br>1<br><br>0<br>EOF


	Also, for entities and preserving of unknown tags:
	
	>>> print c.encode(c.decode('&lt;<foo x="1">foo!</foo>'))
	&lt;<foo x="1">foo!</foo>
	'''

	logger = logging.getLogger(__name__ + '.GmailCodec')
	replace_html = [
		('<div><br></div>', '\n'),
		('<br>', '\n'),
		('<div>', '\n'),
		('</div>', ''),
	]
	replace_text = [
		('\n', '<br>'),
	]

	def _replace(self, content, replacement_pairs):
		for before, after in replacement_pairs:
			if not before: continue
			# self.logger.debug("** Replacing %r -> %r", before, after)
			# self.logger.debug("Before:\n%s", content)
			content = content.replace(before, after)
			# self.logger.debug("After:\n%s", content)
		return content

	def decode(self, content):
		content = self._replace(content, self.replace_html)
		# < and > that are still present need to be distinguishable from actual entities that get decoded to < and >
		content = re.sub('(<|>)', r'_!!\1', content)
		content = html2text.unescape(content)
		return content

	def encode(self, content):
		content = cgi.escape(content)
		content = content.replace('_!!&lt;', '<').replace('_!!&gt;', '>')
		content = self._replace(content, self.replace_text)
		return content
