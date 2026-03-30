from __future__ import print_function, unicode_literals

import sys
import functools
import time
import requests
from datetime import datetime

# Optional Cloudflare bypass helper
try:
  import cloudscraper  # type: ignore
  HAVE_CLOUDSCRAPER = True
except Exception:
  HAVE_CLOUDSCRAPER = False

from fandom.error import HTTPTimeoutError, RequestError

API_URL = 'https://{wiki}.fandom.com/{lang}/api.php'
USER_AGENT = 'fandom (https://github.com/NikolajDanger/fandom-py/)'
RATE_LIMIT = False
RATE_LIMIT_MIN_WAIT = None
RATE_LIMIT_LAST_CALL = None
_SESSION = None

def debug(fn):
  def wrapper(*args, **kwargs):
    print(fn.__name__, 'called!')
    print(sorted(args), tuple(sorted(kwargs.items())))
    res = fn(*args, **kwargs)
    print(res)
    return res
  return wrapper


class cache(object):

  def __init__(self, fn):
    self.fn = fn
    self._cache = {}
    functools.update_wrapper(self, fn)

  def __call__(self, *args, **kwargs):
    key = str(args) + str(kwargs)
    if key in self._cache:
      ret = self._cache[key]
    else:
      ret = self._cache[key] = self.fn(*args, **kwargs)

    return ret

  def clear_cache(self):
    self._cache = {}


# from http://stackoverflow.com/questions/3627793/best-output-type-and-encoding-practices-for-repr-functions
def stdout_encode(u, default='UTF8'):
  encoding = sys.stdout.encoding or default
  if sys.version_info > (3, 0):
    return u.encode(encoding).decode(encoding)
  return u.encode(encoding)

def _get_session():
  """Return a reusable HTTP session, creating it once on first call."""
  global _SESSION
  if _SESSION is None:
    if HAVE_CLOUDSCRAPER:
      _SESSION = cloudscraper.create_scraper()
    else:
      _SESSION = requests.Session()
  return _SESSION

def _wiki_request(params):
  """
  Make a request to the fandom API using the given search parameters.
  Returns a parsed dict of the JSON response.
  """
  global RATE_LIMIT_LAST_CALL
  global USER_AGENT

  api_url = API_URL.format(**params)
  params = params.copy()
  params['format'] = 'json'
  headers = {
    'User-Agent': USER_AGENT
  }

  if RATE_LIMIT and RATE_LIMIT_LAST_CALL and \
    RATE_LIMIT_LAST_CALL + RATE_LIMIT_MIN_WAIT > datetime.now():

    # it hasn't been long enough since the last API call
    # so wait until we're in the clear to make the request

    wait_time = (RATE_LIMIT_LAST_CALL + RATE_LIMIT_MIN_WAIT) - datetime.now()
    time.sleep(int(wait_time.total_seconds()))

  params.pop("wiki")
  params.pop("lang")
  session = _get_session()
  try:
    r = session.get(api_url, params=params, headers=headers)
  except Exception:
    r = requests.get(api_url, params=params, headers=headers)

  if RATE_LIMIT:
    RATE_LIMIT_LAST_CALL = datetime.now()

  if r.status_code == 404:
    raise RequestError(api_url, params)

  # If getting the json representation did not work, our data is mangled
  try:
    r = r.json()
  except Exception:
    text = getattr(r, 'text', None)
    _cf_markers = ("Attention Required", 'cf-browser-verification', 'jschl_vc', 'Cloudflare', 'Just a moment', 'Checking your browser')
    if text and any(m in text for m in _cf_markers):
      if not HAVE_CLOUDSCRAPER:
        raise RequestError(api_url, dict(params, _note='Cloudflare detected; install cloudscraper to bypass'))
      try:
        r = _get_session().get(api_url, params=params, headers=headers).json()
      except Exception:
        raise RequestError(api_url, params)
    else:
      raise RequestError(api_url, params)
  # If we got a json response, then we know the format of the input was correct
  if "exception" in r:
    error_code= r['exception'].values()[2]
    if error_code == 408:
      raise HTTPTimeoutError(params["query"])
    raise RequestError(api_url, params)
  return r
