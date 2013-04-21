#!/usr/bin/python

import logging
import re

import mechanize


CONTENT_TYPE_HEADER = 'Content-Type'
EXTRACT_HTTP_CHARSET_PATTERN = re.compile(r'charset=["\']?([a-zA-Z0-9-_]+)')

logger = logging.getLogger(__name__)


class Browser(mechanize.Browser):
    def __init__(self):
        mechanize.Browser.__init__(self)

        self.set_handle_equiv(True)
        # Still experimental.
        #self.set_handle_gzip(True)
        self.set_handle_redirect(True)
        self.set_handle_referer(True)
        self.set_handle_robots(False)

        # Follows refresh 0 but not hangs on refresh > 0
        #self.set_handle_refresh(
        #        mechanize._http.HTTPRefreshProcessor(), max_time=1)

        # Want debugging messages?
        #self.set_debug_http(True)
        #self.set_debug_redirects(True)
        #self.set_debug_responses(True)

        self.addheaders = [('User-agent', (
                'Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.0.1) '
                'Gecko/2008071615 Fedora/3.0.1-1.fc9 Firefox/3.0.1'))]

    def _decode_content(self, content, content_type_header):
        """Returns the content of a urlfetch.fetch() response as unicode.

        @type content: str
        @param content: The encoded content.

        @type content_type_header: str or None
        @param content_type_header: The Content-Type header, if exists.

        @rtype: unicode
        @return: The decoded content.

        @raise UnicodeDecodeError: If the content could not be decoded.
        """
        encoding = None
        if content_type_header:
            match = EXTRACT_HTTP_CHARSET_PATTERN.search(content_type_header)
            if match:
                encoding = match.group(1)
                logger.debug('Charset from content-type header: %s.' % encoding)
            else:
                logger.debug(
                        'Couldn\'t extract encoding from Content-Type header: '
                        '%s.' % content_type_header)
        else:
            logger.info('No Content-Type header.')

        if not encoding:
            logger.info(
                    'Couldn\'t determine content encoding. '
                    'Fallback to latin-1.')
            encoding = 'iso-8859-1'

        try:
            return content.decode(encoding, 'replace')
        except LookupError:
            logger.info('Unknown encoding %s. Fallback to latin-1.' % encoding)
            encoding = 'iso-8859-1'
            return content.decode(encoding, 'replace')

    def get_decoded_content(self):
        """Returns the decoded browser response as unicode.

        @rtype: unicode
        @return: The decoded content.
        """
        response = self.response()
        content_type_header = response.info().getheader(CONTENT_TYPE_HEADER)
        return self._decode_content(response.read(), content_type_header)
