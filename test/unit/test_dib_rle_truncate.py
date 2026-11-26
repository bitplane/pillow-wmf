from pillow_wmf.dib_rle import truncate_rle

# A run, end of line, a padded absolute run, end of line, a delta, a run,
# end of line and end of bitmap.
STREAM = bytes((3, 1, 0, 0, 0, 3, 1, 2, 3, 0, 0, 0, 0, 2, 1, 1, 2, 7, 0, 0, 0, 1))


def test_rle_streams_end_after_their_band_lines():
    # The second end of line leaves a two-line band and becomes end of bitmap.
    assert truncate_rle(STREAM, 8, 2) == bytes((3, 1, 0, 0, 0, 3, 1, 2, 3, 0, 0, 1))
    # A delta leaving a three-line band ends it too.
    assert truncate_rle(STREAM, 8, 3) == bytes((3, 1, 0, 0, 0, 3, 1, 2, 3, 0, 0, 0, 0, 1))
    assert truncate_rle(STREAM, 8, 9) == STREAM
