namespace OhmyPort.Core.Serial;

/// <summary>校验算法。</summary>
public enum ChecksumKind
{
    None,
    Sum8,
    Xor8,
    Crc16Modbus,
}

/// <summary>切出的一帧：原始字节 + 校验是否通过。</summary>
public readonly record struct Frame(byte[] Data, bool ChecksumOk);

/// <summary>
/// 自定义帧协议解析：按帧头 + 长度字段（或帧尾）从字节流中切帧，并做校验。
///
/// 帧结构约定：[帧头][长度字段?][数据][校验][帧尾]
/// - 长度字段紧跟帧头之后（LengthSize 字节），其值表示数据字节数（可用 LengthBase 微调）。
/// - 校验覆盖 [帧头][长度字段][数据]（即校验字节之前的所有内容）。
/// - 校验字节位于帧尾之前（无帧尾则在末尾）。
/// </summary>
/// <remarks>线程不安全：需在单一接收线程内使用（与 Python 版一致）。</remarks>
public sealed class FrameParser
{
    private readonly List<byte> _buf = [];

    public byte[] Header { get; init; } = [];
    public byte[] Tail { get; init; } = [];
    public int LengthSize { get; init; }
    public int LengthBase { get; init; }
    public bool BigEndian { get; init; } = true;
    public ChecksumKind Checksum { get; init; } = ChecksumKind.None;

    public int ChecksumSize => Checksum switch
    {
        ChecksumKind.Crc16Modbus => 2,
        ChecksumKind.Sum8 or ChecksumKind.Xor8 => 1,
        _ => 0,
    };

    public void Reset() => _buf.Clear();

    /// <summary>喂入一段字节流，返回本次能切出的所有完整帧。</summary>
    public List<Frame> Feed(ReadOnlySpan<byte> data)
    {
        _buf.AddRange(data.ToArray());
        var frames = new List<Frame>();
        while (true)
        {
            var frame = ExtractOne();
            if (frame is null)
            {
                break;
            }

            frames.Add(frame.Value);
        }

        return frames;
    }

    private Frame? ExtractOne()
    {
        if (Header.Length > 0)
        {
            var idx = IndexOf(Header, 0);
            if (idx < 0)
            {
                // 保留可能是帧头前缀的尾巴，其余丢弃
                var keep = Header.Length - 1;
                if (_buf.Count > keep)
                {
                    _buf.RemoveRange(0, _buf.Count - keep);
                }

                return null;
            }

            if (idx > 0)
            {
                _buf.RemoveRange(0, idx);
            }
        }

        var end = FindEnd();
        if (end is null)
        {
            return null;
        }

        var frame = _buf.GetRange(0, end.Value).ToArray();
        _buf.RemoveRange(0, end.Value);
        return new Frame(frame, Check(frame));
    }

    private int? FindEnd()
    {
        var cs = ChecksumSize;

        if (LengthSize > 0)
        {
            var off = Header.Length;
            if (off + LengthSize > _buf.Count)
            {
                return null;
            }

            var lengthValue = 0;
            for (var i = 0; i < LengthSize; i++)
            {
                var b = _buf[off + i];
                lengthValue = BigEndian
                    ? (lengthValue << 8) | b
                    : lengthValue | (b << (8 * i));
            }

            var dataLength = lengthValue + LengthBase;
            var total = Header.Length + LengthSize + dataLength + cs + Tail.Length;
            if (total <= 0 || total > _buf.Count)
            {
                return null;
            }

            return total;
        }

        if (Tail.Length > 0)
        {
            var start = Header.Length;
            var idx = IndexOf(Tail, start);
            return idx < 0 ? null : idx + Tail.Length;
        }

        return null;
    }

    private bool Check(byte[] frame)
    {
        if (Checksum == ChecksumKind.None)
        {
            return true;
        }

        var csSize = ChecksumSize;
        var suffix = csSize + Tail.Length;
        if (suffix == 0 || frame.Length < suffix)
        {
            return false;
        }

        var covered = frame.AsSpan(0, frame.Length - suffix);
        var csBytes = frame.AsSpan(frame.Length - suffix, csSize);

        return Checksum switch
        {
            ChecksumKind.Sum8 => (Sum8(covered) & 0xFF) == csBytes[0],
            ChecksumKind.Xor8 => Xor8(covered) == csBytes[0],
            ChecksumKind.Crc16Modbus => (ushort)(csBytes[0] | (csBytes[1] << 8)) == Crc16Modbus(covered),
            _ => true,
        };
    }

    private int IndexOf(byte[] needle, int start)
    {
        var limit = _buf.Count - needle.Length;
        for (var i = start; i <= limit; i++)
        {
            var hit = true;
            for (var j = 0; j < needle.Length; j++)
            {
                if (_buf[i + j] != needle[j])
                {
                    hit = false;
                    break;
                }
            }

            if (hit)
            {
                return i;
            }
        }

        return -1;
    }

    public static int Sum8(ReadOnlySpan<byte> data)
    {
        var sum = 0;
        foreach (var b in data)
        {
            sum += b;
        }

        return sum;
    }

    public static byte Xor8(ReadOnlySpan<byte> data)
    {
        byte x = 0;
        foreach (var b in data)
        {
            x ^= b;
        }

        return x;
    }

    /// <summary>CRC16-Modbus（多项式 0xA001，初值 0xFFFF）。</summary>
    public static ushort Crc16Modbus(ReadOnlySpan<byte> data)
    {
        ushort crc = 0xFFFF;
        foreach (var b in data)
        {
            crc ^= b;
            for (var i = 0; i < 8; i++)
            {
                crc = (crc & 1) != 0
                    ? (ushort)((crc >> 1) ^ 0xA001)
                    : (ushort)(crc >> 1);
            }
        }

        return crc;
    }

    /// <summary>
    /// 计算校验字节（发送侧自动追加 / 校验计算器共用）。
    /// 返回字节按「帧内存储顺序」排列：CRC16-Modbus 低字节在前（与 <see cref="Check"/> 的比较一致）。
    /// </summary>
    public static byte[] ChecksumBytes(ChecksumKind kind, ReadOnlySpan<byte> data)
    {
        switch (kind)
        {
            case ChecksumKind.Sum8:
                return [(byte)(Sum8(data) & 0xFF)];
            case ChecksumKind.Xor8:
                return [Xor8(data)];
            case ChecksumKind.Crc16Modbus:
            {
                var crc = Crc16Modbus(data);
                return [(byte)(crc & 0xFF), (byte)(crc >> 8)];
            }
            default:
                return [];
        }
    }

    /// <summary>把配置里的字符串（none / sum8 / xor8 / crc16_modbus）转成枚举。</summary>
    public static ChecksumKind ParseChecksum(string? value) => value switch
    {
        ChecksumKeys.Sum8 => ChecksumKind.Sum8,
        ChecksumKeys.Xor8 => ChecksumKind.Xor8,
        ChecksumKeys.Crc16Modbus => ChecksumKind.Crc16Modbus,
        _ => ChecksumKind.None,
    };
}

/// <summary>校验类型配置键（none / sum8 / xor8 / crc16_modbus）。</summary>
public static class ChecksumKeys
{
    public const string None = "none";
    public const string Sum8 = "sum8";
    public const string Xor8 = "xor8";
    public const string Crc16Modbus = "crc16_modbus";
    public static readonly string[] All = [None, Sum8, Xor8, Crc16Modbus];
}
