"""까만 창에 나오는 글을 기록 파일에도 같이 적는다 (밤새 돌린 뒤 무슨 일이 있었는지 보려고)."""

import sys
import time
from contextlib import contextmanager


class Tee:
    def __init__(self, stream, path):
        self.stream = stream
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = open(path, "a", encoding="utf-8")

    def write(self, text):
        self.stream.write(text)
        self.file.write(text)
        self.file.flush()

    def flush(self):
        self.stream.flush()

    def close(self):
        self.file.close()


@contextmanager
def record(path):
    """with record(경로): 안에서 print 한 글을 그 파일에도 적는다. 이미 기록 중이면(일괄 작업) 그대로 둔다."""
    if isinstance(sys.stdout, Tee):
        yield
        return
    try:
        tee = Tee(sys.stdout, path)
    except OSError:
        yield
        return
    old, sys.stdout = sys.stdout, tee
    print(f"\n======== {time.strftime('%Y-%m-%d %H:%M:%S')} 시작 ========")
    try:
        yield
    finally:
        sys.stdout = old
        tee.close()
