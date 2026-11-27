"""EXIF and preparation of the images for the vision model."""
import struct
import zlib

import pytest
from PIL import Image

from app.errors import PermanentError
from app.imaging import dms_to_decimal, prepare, read_exif, tile_boxes

from .conftest import jpeg_size, make_image

FORMATS = ["jpg", "jpeg", "png", "webp", "heic", "tif", "tiff"]


@pytest.mark.parametrize("ext", FORMATS)
def test_exif_in_every_format(tmp_path, ext):  # AK-2, EC-1
    p = make_image(tmp_path / f"foto.{ext}", gps=(44.0596, 12.5683, 3.5))
    info = read_exif(p)
    assert info.taken == "2024-07-12T14:03:22"
    assert info.camera == {"make": "Canon", "model": "EOS R5"}
    assert info.gps["latitude"] == pytest.approx(44.0596, abs=1e-5)
    assert info.gps["longitude"] == pytest.approx(12.5683, abs=1e-5)
    assert info.gps["altitude"] == pytest.approx(3.5)
    assert (info.width, info.height) == (60, 40)
    prep = prepare(p, 1024, 250)
    assert len(prep.jpegs) == 1 and jpeg_size(prep.jpegs[0]) == (60, 40)


def test_gps_south_west_signed(tmp_path):  # AK-8
    p = make_image(tmp_path / "sydney.jpg", gps=(-33.8568, -151.2153, -2.0))
    gps = read_exif(p).gps
    assert gps["latitude"] == pytest.approx(-33.8568, abs=1e-5)
    assert gps["longitude"] == pytest.approx(-151.2153, abs=1e-5)
    assert gps["altitude"] == pytest.approx(-2.0)
    assert dms_to_decimal((33, 51, 24.48), "S") == pytest.approx(-33.8568)


def test_no_exif_is_no_error(tmp_path):  # AK-7
    p = make_image(tmp_path / "screenshot.png", size=(120, 80), exif=False)
    info = read_exif(p)
    assert info.fields() == {"taken": None, "width": 120, "height": 80, "gps": None, "camera": None}


def test_gps_zero_counts_as_none(tmp_path):  # EC-3
    assert read_exif(make_image(tmp_path / "null.jpg", gps=(0.0, 0.0, None))).gps is None


def test_orientation_turns_image_upright(tmp_path):  # EC-10
    p = make_image(tmp_path / "hoch.jpg", size=(300, 200), orientation=6)
    info = read_exif(p)
    assert (info.width, info.height) == (200, 300)
    assert jpeg_size(prepare(p, 1024, 250).jpegs[0]) == (200, 300)


def test_first_frame_of_multipage_tiff(tmp_path):  # EC-9
    p = make_image(tmp_path / "scan.tif", size=(80, 60), frames=3)
    prep = prepare(p, 1024, 250)
    assert len(prep.jpegs) == 1 and jpeg_size(prep.jpegs[0]) == (80, 60)


@pytest.mark.parametrize("size", [(6000, 4000), (4000, 6000), (4000, 2000)])
def test_one_image_up_to_two_to_one(tmp_path, size):  # AK-22
    p = make_image(tmp_path / "gross.jpg", size=size, exif=False)
    prep = prepare(p, 1024, 250)
    assert len(prep.jpegs) == 1 and max(jpeg_size(prep.jpegs[0])) <= 1024


@pytest.mark.parametrize("size", [(22704, 1760), (1760, 22704)])
def test_panorama_in_eight_tiles(tmp_path, size):  # AK-23
    p = make_image(tmp_path / "pano.jpg", size=size, exif=False)
    prep = prepare(p, 1024, 250)
    assert len(prep.jpegs) == 8 and all(max(jpeg_size(j)) <= 1024 for j in prep.jpegs)
    assert prep.landscape == (size[0] > size[1])
    boxes = tile_boxes(*size)
    starts = [b[0] if size[0] > size[1] else b[1] for b in boxes]
    assert starts == sorted(starts) and starts[0] == 0  # left → right / top → bottom
    assert (boxes[-1][2] if size[0] > size[1] else boxes[-1][3]) == max(size)


def _png_header(width, height) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00" * 10)) + chunk(b"IEND", b""))


def test_over_pixel_limit_without_decoding(tmp_path):  # AK-25
    p = tmp_path / "riesig.png"
    p.write_bytes(_png_header(20000, 13000))  # 260 MP in the header, no pixel data
    with pytest.raises(PermanentError, match="Bild zu groß .*260 MP.*250 MP"):
        prepare(str(p), 1024, 250)


def test_broken_file(tmp_path):  # AK-25
    p = tmp_path / "kaputt.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
    with pytest.raises(PermanentError, match="nicht lesbar"):
        prepare(str(p), 1024, 250)
    with pytest.raises(PermanentError):
        read_exif(str(p))


def test_truncated_jpeg_is_read_tolerant(tmp_path):
    p = make_image(tmp_path / "ok.jpg", size=(400, 300), exif=False)
    data = open(p, "rb").read()
    (tmp_path / "cut.jpg").write_bytes(data[:-200])
    assert len(prepare(str(tmp_path / "cut.jpg"), 1024, 250).jpegs) == 1


def test_missing_file_is_os_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        prepare(str(tmp_path / "weg.jpg"), 1024, 250)


def test_palette_and_alpha(tmp_path):
    p = tmp_path / "logo.png"
    Image.new("RGBA", (50, 50), (0, 0, 0, 0)).save(p)
    assert len(prepare(str(p), 1024, 250).jpegs) == 1
