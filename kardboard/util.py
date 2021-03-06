import datetime
import re
import traceback
import logging
from logging.handlers import RotatingFileHandler
import os
import functools

import jinja2.ext
import markdown2

from flaskext.mongoengine import MongoEngine
from werkzeug.contrib.cache import RedisCache
import mongoengine


import translitcodec
from dateutil.relativedelta import relativedelta


class ImproperlyConfigured(Exception):
    pass


def redirect_to_next_url(fn):
    """
    Views wrapped in this decorator will
    look for a 'next_url' in the session or
    as a query string in the URL. If the view
    returns True (not a value that equates to True)
    then the user is redirected to next_url.
    """
    @functools.wraps(fn)
    def _wrapped_view_fn(*args, **kwargs):
        from flask import session, redirect, request
        if not session.get('next_url'):
            next_url = request.args.get('next', '/')
            session['next_url'] = next_url

        # Call the decorated function
        retval = fn(*args, **kwargs)

        if retval == True:
            next_url = session.get('next_url', '/')
            if 'next_url' in session:
                del session['next_url']
            return redirect(next_url)

        # Must not need the redirect, return the original return value
        return retval
    return _wrapped_view_fn


def redis_cache(app, args, kwargs):
    timeout = app.config.get('CACHE_DEFAULT_TIMEOUT', 300)
    return RedisCache(default_timeout=timeout)


def now():
    return datetime.datetime.now()


def get_current_app():
    from kardboard.app import app
    return app


def log_exception(exc, msg=""):
    tb = traceback.format_exc()
    log_msg = [msg, str(exc), tb]
    log_msg = '\n'.join(log_msg)
    app = get_current_app()
    app.logger.critical(log_msg)


def business_days_between(date1, date2):
    if date1 < date2:
        oldest_date, youngest_date = date1, date2
    else:
        oldest_date, youngest_date = date2, date1

    business_days = 0
    date = oldest_date
    while date < youngest_date:
        if date.weekday() != 5 and date.weekday() != 6:
            business_days += 1
        date = date + datetime.timedelta(days=1)
    return business_days


def month_ranges(date, num_months):
    if num_months == 1:
        return [month_range(date), ]
    end_start, end_end = month_range(date)
    months_ago = end_start - relativedelta(months=num_months - 1)

    start_start, start_end = month_range(months_ago)

    month_ranges = [(start_start, start_end), ]

    for i in xrange(0, num_months - 2):
        next_month = month_ranges[-1][0] + relativedelta(months=1)
        start, end = month_range(date=next_month)
        month_ranges.append((start, end))
    month_ranges.append((end_start, end_end))

    return month_ranges


def month_range(date):
    start = date.replace(day=1)
    end = start + relativedelta(months=+1) + relativedelta(days=-1)

    start, end = make_start_date(date=start), make_end_date(date=end)
    return start, end


def week_range(date):
    day_type = date.isoweekday()  # 1-7
    if day_type == 7:
        start_date = date
    else:
        start_date = date - relativedelta(days=day_type)
    end_date = start_date + relativedelta(days=6)

    start_date = make_start_date(date=start_date)
    end_date = make_end_date(date=end_date)

    return start_date, end_date


def make_start_date(year=None, month=None, day=None, date=None):
    start_date = munge_date(year, month, day, date)
    start_date = start_date.replace(hour=23, minute=59, second=59)
    start_date = start_date.replace(hour=0, minute=0, second=0)
    return start_date


def make_end_date(year=None, month=None, day=None, date=None):
    end_date = munge_date(year, month, day, date)
    end_date = end_date.replace(hour=23, minute=59, second=59)
    return end_date


def munge_date(year=None, month=None, day=None, date=None):
    """
    Takes a given datetime, or now(), and sets its
    year, month and day to any of those values passed in
    optionally.
    """
    if not date:
        date = datetime.datetime.now()

    year = year or date.year
    month = month or date.month
    day = day or date.day

    date = date.replace(year=year, month=month, day=day, microsecond=0)
    return date

_punct_re = re.compile(r'[\t !"#$%&\'()*\-/<=>?@\[\\\]^_`{|},.]+')


def slugify(text, delim=u'-'):
    """Generates an ASCII-only slug."""
    result = []
    for word in _punct_re.split(text.lower()):
        word = word.encode('translit/long')
        if word:
            result.append(word)
    return unicode(delim.join(result))


def timesince(dt, default="just now"):
    """
    Returns string representing "time since" e.g.
    3 days ago, 5 hours ago etc.
    """

    now = datetime.datetime.now()
    diff = now - dt

    periods = (
        (diff.days / 365, "year", "years"),
        (diff.days / 30, "month", "months"),
        (diff.days / 7, "week", "weeks"),
        (diff.days, "day", "days"),
        (diff.seconds / 3600, "hour", "hours"),
        (diff.seconds / 60, "minute", "minutes"),
        (diff.seconds, "second", "seconds"),
    )

    for period, singular, plural in periods:

        if period:
            return "%d %s ago" % (period, singular if period == 1 else plural)

    return default


def jsonencode(data):
    import json
    return json.dumps(data)


def get_newrelic():
    try:
        import newrelic
        return newrelic
    except ImportError:
        return None


def get_newrelic_agent():
    try:
        import newrelic.agent
        return newrelic.agent
    except ImportError:
        return None


def newrelic_head():
    agent = get_newrelic_agent()
    if agent:
        content = [
            '<!-- New Relic tracking -->'
        ]
        header = agent.get_browser_timing_header()
        content.append(header)
        return '\n'.join(content)
    return ''


def newrelic_foot():
    agent = get_newrelic_agent()
    if agent:
        content = [
            '<!-- New Relic tracking -->'
        ]
        footer = agent.get_browser_timing_footer()
        content.append(footer)
        return '\n'.join(content)
    return ''


class PortAwareMongoEngine(MongoEngine):
    def init_app(self, app):
        db = app.config['MONGODB_DB']
        username = app.config.get('MONGODB_USERNAME', None)
        password = app.config.get('MONGODB_PASSWORD', None)
        port = app.config.get('MONGODB_PORT', 27017)

        # more settings e.g. port etc needed

        try:
            self.connection = mongoengine.connect(
                db=db, username=username, password=password, port=port)
        except mongoengine.connection.ConnectionError:
            # Useful for when code is accessed, like say a sphinx docs
            # build and there's no database running.
            self.connection = None


def configure_logging(app):
    LEVELS = {'debug': logging.DEBUG,
              'info': logging.INFO,
              'warning': logging.WARNING,
              'error': logging.ERROR,
              'critical': logging.CRITICAL}

    if app.config.get('LOG_FILE'):
        log_file = app.config['LOG_FILE']
        log_file = os.path.abspath(os.path.expanduser(log_file))
        new_handler = RotatingFileHandler(
            log_file, maxBytes=100000, backupCount=3)
        if app.config.get('LOG_LEVEL'):
            new_level = app.config['LOG_LEVEL']
            new_level = LEVELS.get(new_level, logging.error)
            new_handler.setLevel(new_level)

        log_format = (
            '-' * 80 + '\n' +
            '%(asctime)-15s\n%(levelname)s in %(module)s [%(pathname)s:%(lineno)d]:\n' +
            '%(message)s\n' +
            '-' * 80
        )
        new_handler.setFormatter(logging.Formatter(log_format))

        app.logger.addHandler(new_handler)


class Markdown2Extension(jinja2.ext.Extension):
    tags = set(['markdown2'])

    def __init__(self, environment):
        super(Markdown2Extension, self).__init__(environment)
        environment.extend(
            markdowner=markdown2.Markdown()
        )

    def parse(self, parser):
        lineno = parser.stream.next().lineno
        body = parser.parse_statements(
            ['name:endmarkdown2'],
            drop_needle=True
        )
        return jinja2.nodes.CallBlock(
            self.call_method('_markdown_support'),
            [],
            [],
            body
        ).set_lineno(lineno)

    def _markdown_support(self, caller):
        return self.environment.markdowner.convert(caller()).strip()


class FixGunicorn(object):
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        environ['SERVER_PORT'] = int(environ['SERVER_PORT'])
        return self.app(environ, start_response)
