"""FrameParser 单元测试。"""

import frame_parser as fp


def test_header_tail():
    p = fp.FrameParser(header=bytes.fromhex("AA55"), tail=bytes.fromhex("0D0A"))
    out = p.feed(bytes.fromhex("AA 55 01 02 0D 0A"))
    assert out == [(bytes.fromhex("AA 55 01 02 0D 0A"), True)]


def test_length_field():
    # 帧头 AA，长度字段 1 字节紧跟其后，数据长度 2
    p = fp.FrameParser(header=b"\xAA", length_size=1)
    out = p.feed(b"\xAA\x02\x01\x02")
    assert out == [(b"\xAA\x02\x01\x02", True)]


def test_fragmented():
    p = fp.FrameParser(header=b"\xAA\x55", tail=b"\x0D\x0A")
    assert p.feed(b"\xAA") == []
    assert p.feed(b"\x55\x01") == []
    out = p.feed(b"\x02\x0D\x0A")
    assert out == [(bytes.fromhex("AA 55 01 02 0D 0A"), True)]


def test_sum8():
    # 覆盖 [长度字段][数据]：3 + 1 + 2 + 3 = 9
    p = fp.FrameParser(length_size=1, checksum="sum8")
    good = bytes([3, 1, 2, 3, 9])
    assert p.feed(good) == [(good, True)]
    p2 = fp.FrameParser(length_size=1, checksum="sum8")
    bad = bytes([3, 1, 2, 3, 7])
    assert p2.feed(bad) == [(bad, False)]


def test_xor8():
    # 覆盖 [3,1,2,3]，xor = 3^1^2^3 = 3
    p = fp.FrameParser(length_size=1, checksum="xor8")
    good = bytes([3, 1, 2, 3, 3])
    assert p.feed(good) == [(good, True)]


def test_crc16_modbus():
    data = bytes.fromhex("01 03 00 00 00 0A")
    crc = fp._crc16_modbus(bytes([6]) + data)  # 覆盖长度字段 + 数据
    crc_bytes = crc.to_bytes(2, "little")
    p = fp.FrameParser(length_size=1, checksum="crc16_modbus")
    frame = bytes([6]) + data + crc_bytes
    assert p.feed(frame) == [(frame, True)]
