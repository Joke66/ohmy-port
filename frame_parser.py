"""自定义帧协议解析：按帧头 + 长度字段（或帧尾）从字节流中切帧，并做校验。

帧结构约定：[帧头][长度字段?][数据][校验][帧尾]
- 长度字段紧跟帧头之后（length_size 字节），其值表示数据字节数（可用 length_base 微调）。
- 校验覆盖 [帧头][长度字段][数据]（即校验字节之前的所有内容）。
- 校验字节位于帧尾之前（无帧尾则在末尾）。
"""

from __future__ import annotations


def _crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc


class FrameParser:
    """增量式帧解析器（线程不安全，需在单一接收线程内使用）。"""

    def __init__(self, header: bytes = b"", tail: bytes = b"",
                 length_size: int = 0, length_base: int = 0,
                 length_endian: str = "big", checksum: str = "none"):
        self.header = bytes(header)
        self.tail = bytes(tail)
        self.length_size = length_size
        self.length_base = length_base
        self.length_endian = length_endian
        self.checksum = checksum
        self._buf = bytearray()

    @property
    def checksum_size(self) -> int:
        if self.checksum == "crc16_modbus":
            return 2
        if self.checksum in ("sum8", "xor8"):
            return 1
        return 0

    def reset(self) -> None:
        self._buf.clear()

    def feed(self, data: bytes) -> list[tuple[bytes, bool]]:
        self._buf += data
        out: list[tuple[bytes, bool]] = []
        while True:
            frame = self._extract_one()
            if frame is None:
                break
            out.append(frame)
        return out

    # ---------- 内部 ----------
    def _extract_one(self) -> tuple[bytes, bool] | None:
        buf = self._buf
        if self.header:
            idx = buf.find(self.header)
            if idx < 0:
                keep = len(self.header) - 1
                if len(buf) > keep:
                    del buf[: len(buf) - keep]
                return None
            if idx > 0:
                del buf[:idx]

        end = self._find_end(buf)
        if end is None:
            return None
        frame = bytes(buf[:end])
        del buf[:end]
        return frame, self._check(frame)

    def _find_end(self, buf: bytearray) -> int | None:
        cs = self.checksum_size
        if self.length_size > 0:
            off = len(self.header)
            if off + self.length_size > len(buf):
                return None
            length_value = int.from_bytes(
                buf[off:off + self.length_size], self.length_endian)
            data_length = length_value + self.length_base
            total = len(self.header) + self.length_size + data_length + cs + len(self.tail)
            if total <= 0 or total > len(buf):
                return None
            return total
        if self.tail:
            start = len(self.header) if self.header else 0
            idx = buf.find(self.tail, start)
            if idx < 0:
                return None
            return idx + len(self.tail)
        return None

    def _check(self, frame: bytes) -> bool:
        if self.checksum == "none":
            return True
        cs_size = self.checksum_size
        suffix = cs_size + len(self.tail)
        if suffix == 0 or len(frame) < suffix:
            return False
        covered = frame[: len(frame) - suffix]
        cs_bytes = frame[len(frame) - suffix: len(frame) - len(self.tail)]
        if self.checksum == "sum8":
            return (sum(covered) & 0xFF) == cs_bytes[0]
        if self.checksum == "xor8":
            x = 0
            for b in covered:
                x ^= b
            return x == cs_bytes[0]
        if self.checksum == "crc16_modbus":
            return int.from_bytes(cs_bytes, "little") == _crc16_modbus(covered)
        return True
