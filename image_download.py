#!/usr/bin/python3

from contextlib import contextmanager, suppress

import os
import queue
import sys
import termios
import threading
import time
import traceback
import urllib3

ca_pem=os.path.join(os.path.dirname(__file__), 'ca.pem')

@contextmanager
def create_file(filename, size=None, mode=0o444):
    """'best practices' atomic file creation with O_TMPFILE and posix_fallocate()"""
    directory = os.path.normpath(os.path.join(filename, '..'))
    os.makedirs(directory, exist_ok=True)
    file = os.fdopen(os.open(directory, os.O_WRONLY | os.O_TMPFILE, mode), 'wb')
    try:
        # before
        if size is not None:
            os.posix_fallocate(file.fileno(), 0, size)

        yield file

        # after, in case of no exception
        file.flush()
        os.fdatasync(file.fileno())
        with suppress(FileExistsError):
            # HACK: src_dir_fd is ignored (because src is absolute) but
            # we need to specify it to force Python to use linkat().
            # See https://bugs.python.org/issue37612
            os.link('/proc/self/fd/{}'.format(file.fileno()), filename, src_dir_fd=0)
    finally:
        file.close()

class CockpitManager(urllib3.PoolManager):
    def connection_from_context(self, context):
        # if it has ':' or if it has no letters, then it's an IP → use cockpit-tests as the TLS verification name
        if ':' in context['host'] or not any(c.isalpha() for c in context['host']):
            context['server_hostname'] = 'cockpit-tests'
        return super(CockpitManager, self).connection_from_context(context)

def worker(prefix, suffix, status_queue, work_queue):
    try:
        url = prefix + suffix
        http = CockpitManager(ca_certs=ca_pem, timeout=2.0, retries=1)

        # First, do HEAD to find out if the file is there and discover the size
        request = http.request('HEAD', url)
        if request.status != 200:
            status_queue.put((prefix, 'error', str(request.status)))
            return
        try:
            status_queue.put((prefix, 'size', int(request.headers['Content-Length'])))
        except (KeyError, ValueError):
            status_queue.put((prefix, 'error', 'Content-Length not reported'))
            return

        # Now, process blocks from the work queue
        while block := work_queue.get():
            try:
                filename, (start, end) = block

                if not os.path.exists(filename):
                    # Request the block
                    headers = {'Range': 'bytes={}-{}'.format(start, end - 1)}
                    request = http.request('GET', url, headers=headers, preload_content=False)

                    if request.status != 206:
                        status_queue.put((prefix, 'error', str(request.status)))
                        return

                    # Download it to disk
                    with create_file(filename, end - start) as output:
                        for chunk in request.stream():
                            status_queue.put((prefix, 'progress', len(chunk)))
                            output.write(chunk)
                else:
                    status_queue.put((None, 'progress', end - start))

                # success
                status_queue.put((prefix, 'block', block))
                block = None

            except urllib3.exceptions.ReadTimeoutError:
                pass # loop around and try to connect again with a new request

            finally:
                # if we failed to handle the block, put it back in the queue
                if block is not None:
                    work_queue.put(block)
                # release the connection back to the pool so it can be reused
                request.release_conn()

    except urllib3.exceptions.MaxRetryError as e:
        status_queue.put((prefix, 'error', e.reason))

    except Exception as e: # shouldn't happen
        traceback.print_exc()
        status_queue.put(None) # will crash the main thread

def make_blocks(directory, size, block_size=1024*1024):
    template = '{directory}/{index:0{width}} of {parts}'
    parts = (size + block_size - 1) // block_size
    width = len(str(parts))

    for index, start in enumerate(range(0, size, block_size), start=1):
        end = min(start + block_size, size)
        filename = template.format(directory=directory, index=index, width=width, parts=parts)
        yield filename, (start, end)

def gather_blocks(destination, blocks):
    with create_file(destination) as result:
        for filename, (start, end) in blocks:
            src = open(filename, 'rb')
            src_size = os.fstat(src.fileno()).st_size

            assert src_size == end - start
            os.copy_file_range(src.fileno(), result.fileno(), src_size, 0, start)
            src.close()

def download(destination, prefixes, suffix, ui):
    n_workers = len(prefixes)
    partialdir = destination + ".partial"

    work_queue = queue.Queue()
    status_queue = queue.Queue()

    ui.start()

    # One worker per prefix
    threads = {}
    for prefix in prefixes:
        args = (prefix, suffix, status_queue, work_queue)
        threads[prefix] = threading.Thread(target=worker, args=args, daemon=True)
        threads[prefix].start()

    size = None
    all_blocks = []
    todo = set(threads) # each thread needs to report size, or error

    # main loop.  this continues for as long as any thread is running.
    while todo:
        try:
            prefix, report, detail = status_queue.get(timeout=1)

            if report == 'size':
                ui.report_size(prefix, detail)

                if size is None: # this is the first size report
                    os.makedirs(destination + '.partial', exist_ok=True)
                    for block in make_blocks(partialdir, detail):
                        all_blocks.append(block)
                        work_queue.put(block)
                        todo.add(block)

                    size = detail
                elif detail != size:
                    ui.fatal('inconsistent size')
                    return
                todo.remove(prefix)

            elif report == 'error':
                ui.report_error(prefix, detail)
                threads[prefix].join()
                del threads[prefix]
                todo.remove(prefix)

                if not threads:
                    ui.fatal('unable to download file from any host')
                    return

            elif report == 'progress':
                ui.report_progress(prefix, detail)

            elif report == 'block':
                ui.report_block(prefix, detail)
                todo.remove(detail)

            else:
                raise ValueError('Unknown message type', report)

            ui.refresh()

        except queue.Empty:
            ui.refresh()

    # Assemble the file from all of the downloaded blocks
    gather_blocks(destination, all_blocks)

    # Remove the temporary directory
    for filename, (start, end) in all_blocks:
        os.unlink(filename)
    os.rmdir(partialdir)

    # done!
    ui.finish()


class UI:
    def __init__(self, filename, prefixes):
        self.filename = filename
        self.prefixes = prefixes

    def start(self):
        pass

    def report_size(self, prefix, size):
        pass

    def report_error(self, prefix, error):
        pass

    def report_progress(self, prefix, size):
        pass

    def report_block(self, prefix, size):
        pass

    def refresh(self):
        pass

    def fatal(self, msg):
        pass

    def finish(self):
        pass

class LogfileUI(UI):
    def start(self):
        # initialise the legend
        self.legend = dict((p, chr(c)) for c, p in enumerate(self.prefixes, ord('a')))

        print('Downloading', self.filename, 'from:')

        for prefix in self.prefixes:
            print(' ', self.legend[prefix], prefix)
        print()

    def report_size(self, prefix, size):
        print()
        print(prefix, 'reported a size of', size)
        print()

    def report_error(self, prefix, error):
        print()
        print(prefix, 'reported an error', error)
        print()

    def report_block(self, prefix, block):
        filename, (start, end) = block
        print('[{}:{}]'.format(self.legend[prefix], os.path.basename(filename)), end='', flush=True)

    def finish(self):
        print()
        print('successfully downloaded', self.filename)

    def fatal(self, msg):
        print()
        print('download failed:', msg)

def format_size(n, unit='B'):
    """format a number

    SI, round down, show one decimal place only for values < 10
    """
    groups = f'{n:_}'.split('_')
    whole = groups.pop(0)
    decimal = '.' + groups[0][0] if len(whole) == 1 and groups else ''
    prefix = ' kMGTP'[len(groups)] if groups else ''
    return whole + decimal + prefix + unit

def format_speed(n, elapsed):
    if elapsed < 1 or not n:
        return ''

    return format_size(n / elapsed, unit='B/s')

class FancyUI(UI):
    def start(self):
        self.prefixlen = max(len(prefix) for prefix in self.prefixes)

        self.progress = {prefix:0 for prefix in self.prefixes}
        self.block_progress = {prefix:0 for prefix in self.prefixes}
        self.error = {}

        self.start_time = time.monotonic()
        self.fatal_error = None
        self.total = 0
        self.size = None

        self.refresh(cursor_up=False)

    def report_progress(self, prefix, size):
        if prefix:
            self.progress[prefix] += size
            self.block_progress[prefix] += size
        self.total += size

    def report_error(self, prefix, error):
        # urllib3 exception handling is completely and utterly bonkers.  We
        # lose the original exception and get only a formatted string with lots
        # of junk in it.  Also: for some reason, NewConnectionError is a
        # subclass of ConnectTimeoutError, so don't change the order below.
        if isinstance(error, str):
            reason = error
        elif isinstance(error, urllib3.exceptions.NewConnectionError):
            _, _, reason = error.args[0].partition('] ')
        elif isinstance(error, urllib3.exceptions.ConnectTimeoutError):
            reason = 'Connection timeout'
        elif isinstance(error, urllib3.exceptions.SSLError):
            reason = 'Certificate error: ' + str(error.args[0])
        else:
            reason = 'unknown error ' + str(error.__class__) + ': ' + str(error)

        self.error[prefix] = reason

        self.progress[prefix] -= self.block_progress[prefix]
        self.total -= self.block_progress[prefix]

    def report_block(self, prefix, block):
        self.block_progress[prefix] = 0

    def report_size(self, prefix, size):
        self.size = size

    def refresh(self, cursor_up=True):
        elapsed = time.monotonic() - self.start_time
        width = 120

        if cursor_up:
            sys.stdout.write('\x1b[{}A\x1b[?7l\n'.format(len(self.prefixes) + 2))

        heading_template = '\x1b[K\x1b[{color}m{self.filename}\x1b[m{progress:>17} {speed}\n'
        prefix_template = '  \x1b[K\x1b[{color}m{prefix:<{self.prefixlen}}\x1b[m {progress:>10} \x1b[{status_color}m{status}\x1b[m\n'\

        if self.fatal_error:          # fatal error
            color = '1;31'
        elif self.size is None:       # not downloading yet
            color = '0'
        elif self.total < self.size:  # started downloading
            color = '1;36'
        else:                         # done
            color = '1;32'

        if self.size:
            progress = format_size(self.total) + ' of ' + format_size(self.size)
            speed = format_speed(self.total, elapsed)
        else:
            progress = ''
            speed = ''

        sys.stdout.write(heading_template.format(**vars()))
        for prefix in self.prefixes:
            if self.progress[prefix]:
                progress = format_size(self.progress[prefix])
            else:
                progress = ''

            if prefix in self.error:
                status = self.error[prefix]
                status_color = '1;31'
                color = '1;30'
            else:
                status = format_speed(self.progress[prefix], elapsed)
                status_color = ''
                color = '1;36'

            sys.stdout.write(prefix_template.format(**vars()))

        sys.stdout.write('\x1b[?7h')

    def fatal(self, msg):
        self.fatal_error = msg
        self.refresh()
        print('fatal', msg)

# If we're on a TTY, create a fancy UI.  Otherwise, assume it's a logfile.
@contextmanager
def create_ui(filename, prefixes):
    try:
        saved_tcattr = termios.tcgetattr(1) #stdout
    except termios.error:
        saved_tcattr = None

    if saved_tcattr is not None:
        try:
            # disable echo
            noecho_tcattr = list(saved_tcattr)
            noecho_tcattr[3] &= ~termios.ECHO # 3 = lflag
            termios.tcsetattr(1, termios.TCSANOW, noecho_tcattr)

            yield FancyUI(filename, prefixes)

        finally:
            # restore echo
            termios.tcsetattr(1, termios.TCSANOW, saved_tcattr)

    else:
        # not a terminal
        yield LogfileUI(filename, prefixes)

def get_image(destination):
    prefixes = [
        'https://images-frontdoor.apps.ocp.ci.centos.org/',
        'https://images-cockpit.apps.ci.centos.org/',
        'https://cockpit-11.e2e.bos.redhat.com:8493/',
        'https://10.29.163.169:8493/'
    ]

    path = os.path.basename(destination)

    with create_ui(path, prefixes) as ui:
        download(destination, prefixes, path, ui)

def main():
    get_image(sys.argv[1])

if __name__ == '__main__':
    main()
