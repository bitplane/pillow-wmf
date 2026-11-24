"""Shared fonts give identical results when used from several threads."""

import pickle
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pillow_wmf import Font, FontCollection, FontFace, Recorder, render

LAYOUT = Path(__file__).resolve().parents[1] / "fonts/layout.ttf"
HEIGHTS = tuple(range(-12, -28, -1))
THREADS = 8


def _wmf(height, quality):
    recorder = Recorder(trace_calls=False)
    recorder.select_object(recorder.create_font(Font(height=height, quality=quality, face_name=b"Pillow WMF Test")))
    recorder.text_out(0, 0, b"AB BA AAB")
    return recorder.to_bytes()


def _concurrently(work):
    # Release every worker at once so realizations overlap.
    barrier = threading.Barrier(THREADS)

    def run(worker):
        barrier.wait()
        return work(worker)

    with ThreadPoolExecutor(THREADS) as pool:
        return list(pool.map(run, range(THREADS)))


def test_shared_collection_renders_match_serial_renders():
    jobs = [(height, quality) for height in HEIGHTS for quality in (3, 5)]
    expected = {
        job: render(_wmf(*job), (160, 48), fonts=FontCollection([FontFace.from_path(LAYOUT)])).tobytes() for job in jobs
    }
    shared = FontCollection([FontFace.from_path(LAYOUT)])

    def work(worker):
        # Each worker visits every size, starting at a different one.
        order = jobs[worker * len(jobs) // THREADS :] + jobs[: worker * len(jobs) // THREADS]
        return [job for job in order if render(_wmf(*job), (160, 48), fonts=shared).tobytes() != expected[job]]

    assert _concurrently(work) == [[]] * THREADS


def test_shared_face_glyphs_match_serial_glyphs():
    reference = FontFace.from_path(LAYOUT)
    expected = {height: reference.at_size(height, quality=4).glyph("A", 1 << 20) for height in range(8, 40)}
    shared = FontFace.from_path(LAYOUT)

    def work(worker):
        return [
            height
            for height in sorted(expected, key=lambda h: (h * (worker + 1)) % 37)
            if shared.at_size(height, quality=4).glyph("A", 1 << 20) != expected[height]
        ]

    assert _concurrently(work) == [[]] * THREADS


def test_fonts_remain_picklable_without_realized_sizes():
    face = FontFace.from_path(LAYOUT)
    face.at_size(16).glyph("A", 1 << 20)
    copy = pickle.loads(pickle.dumps(face))
    assert copy._sizes == {} and copy.at_size(16).glyph("A", 1 << 20) == face.at_size(16).glyph("A", 1 << 20)
    collection = pickle.loads(pickle.dumps(FontCollection([face], symbol_fallback=True)))
    assert collection.resolve(Font(face_name=b"Symbol")).symbol
